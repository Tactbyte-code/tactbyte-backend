from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime, timezone, timedelta
from firebase_admin import auth as firebase_auth
import random
import uuid

from src.core.security import get_password_hash, verify_password
from src.app.user.model import User, OTPRecord
from src.app.user.schema import (
    GoogleSignUp,
    EmailSignUp,
    CheckProviderRequest,
    ForgotPasswordRequest,
    VerifyOTPRequest,
    ResetPasswordRequest,
)
from src.app.user.services import get_user_by_email
from src.app.utils.email import send_otp_email
from src.app.activity import services as activity_services


async def check_provider(body: CheckProviderRequest, db: AsyncSession) -> dict:
    user = await get_user_by_email(body.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    provider = "google" if user.hashed_password is None else "email"
    return {"provider": provider}


async def google_auth(body: GoogleSignUp, db: AsyncSession) -> User:
    user = await get_user_by_email(body.email)
    if user:
        # Returning user — record login activity
        await activity_services.ping_user(db, user.id, "login")
        return user

    user = User(
        firebase_uid=body.firebase_uid,
        full_name=body.full_name,
        email=body.email,
        photo_url=body.photo_url,
        hashed_password=None,
    )
    db.add(user)
    await db.flush()  # flush to get user.id before pinging

    # New user — record register activity
    await activity_services.ping_user(db, user.id, "register")
    return user


async def email_signup(body: EmailSignUp, db: AsyncSession) -> User:
    user = await get_user_by_email(body.email)
    if user:
        return user

    user = User(
        firebase_uid=body.firebase_uid,
        full_name=body.full_name,
        email=body.email,
        hashed_password=get_password_hash(body.password),
    )
    db.add(user)
    await db.flush()

    # New user — record register activity
    await activity_services.ping_user(db, user.id, "register")
    return user


async def email_login(body: EmailSignUp, db: AsyncSession) -> User:
    user = await get_user_by_email(body.email)
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email")

    if user.hashed_password is None:
        raise HTTPException(
            status_code=400,
            detail="This account uses Google Sign-In. Please continue with Google.",
        )

    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password")

    # Successful login — record login activity
    await activity_services.ping_user(db, user.id, "login")
    return user


async def send_forgot_password_otp(body: ForgotPasswordRequest, db: AsyncSession) -> dict:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email")

    await db.execute(
        delete(OTPRecord).where(
            OTPRecord.email == body.email,
            OTPRecord.is_used == False,
        )
    )

    otp = str(random.randint(100000, 999999))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.add(OTPRecord(email=body.email, otp=otp, expires_at=expires_at))
    await db.flush()

    try:
        send_otp_email(body.email, otp)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to send OTP email. Check RESEND_API_KEY.")

    return {"message": "OTP sent to your email"}


async def verify_otp(body: VerifyOTPRequest, db: AsyncSession) -> dict:
    result = await db.execute(
        select(OTPRecord).where(
            OTPRecord.email == body.email,
            OTPRecord.otp == body.otp,
            OTPRecord.is_used == False,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    if datetime.now(timezone.utc) > record.expires_at:
        raise HTTPException(status_code=400, detail="OTP has expired")

    reset_token = str(uuid.uuid4())
    record.reset_token = reset_token
    record.is_used = True
    await db.flush()

    return {"reset_token": reset_token}


async def reset_password(body: ResetPasswordRequest, db: AsyncSession) -> dict:
    result = await db.execute(
        select(OTPRecord).where(
            OTPRecord.reset_token == body.reset_token,
            OTPRecord.is_used == True,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if datetime.now(timezone.utc) > record.expires_at + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="Reset token has expired")

    result = await db.execute(select(User).where(User.email == record.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(body.new_password)
    await db.flush()

    try:
        firebase_auth.update_user(user.firebase_uid, password=body.new_password)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    await db.delete(record)
    await db.flush()

    return {"message": "Password reset successfully"}