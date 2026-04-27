import asyncio
import hashlib
import random
import secrets
import string
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core import security
from src.app.admin.model import Admin
from src.app.admin.schema import (
    AdminLoginForm,
    ForgotPasswordRequest,
    VerifyOtpRequest,
    ResetPasswordRequest,
)
from src.app.utils.send_otp_email import send_otp_email

OTP_TTL_MINUTES         = 10
OTP_MAX_ATTEMPTS        = 5
RESET_TOKEN_TTL_MINUTES = 15


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _hash_otp(otp: str) -> str:
    """SHA-256 hash so raw OTP is never stored at rest."""
    return hashlib.sha256(otp.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.utcnow()  # naive UTC — matches TIMESTAMP WITHOUT TIME ZONE


def _is_expired(expiry: datetime | None) -> bool:
    if expiry is None:
        return True
    return datetime.utcnow() > expiry  # both naive, direct compare


# ── Login ─────────────────────────────────────────────────────────────────────

async def login(body: AdminLoginForm, db: AsyncSession) -> dict:
    result = await db.execute(select(Admin).where(Admin.email == body.email))
    admin  = result.scalar_one_or_none()

    if not admin or not security.verify_password(body.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    await db.commit()

    access_token  = security.authX.create_access_token(uid=str(admin.id))
    refresh_token = security.authX.create_refresh_token(uid=str(admin.id))

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "admin": {
            "email":       admin.email,
            "full_name":   admin.name,
            "role":        admin.role,
            "permissions": admin.permissions,
        },
    }


# ── Logout ────────────────────────────────────────────────────────────────────

async def logout() -> dict:
    return {"message": "Logged out successfully."}


# ── Refresh ───────────────────────────────────────────────────────────────────

async def refresh(token) -> dict:
    return {"access_token": security.authX.create_access_token(uid=token.sub)}


# ── Step 1 — Send OTP ─────────────────────────────────────────────────────────

async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession) -> dict:
    result = await db.execute(select(Admin).where(Admin.email == body.email))
    admin  = result.scalar_one_or_none()

    generic_ok = {"message": "If that email is registered, an OTP has been sent."}

    if not admin:
        return generic_ok

    otp = _generate_otp()

    admin.otp_hash           = _hash_otp(otp)
    admin.otp_expiry         = _utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
    admin.otp_attempts       = 0
    admin.reset_token        = None
    admin.reset_token_expiry = None
    await db.commit()

    try:
        await asyncio.to_thread(send_otp_email, admin.email, admin.name, otp)
    except Exception as err:
        admin.otp_hash     = None
        admin.otp_expiry   = None
        await db.commit()
        print(f"❌ OTP email failed for {admin.email}: {err}")
        raise HTTPException(
            status_code=500,
            detail="Failed to send OTP email. Please try again or contact support.",
        )

    return generic_ok


# ── Step 2 — Verify OTP ───────────────────────────────────────────────────────

async def verify_otp(body: VerifyOtpRequest, db: AsyncSession) -> dict:
    result = await db.execute(select(Admin).where(Admin.email == body.email))
    admin  = result.scalar_one_or_none()

    invalid_err = HTTPException(status_code=400, detail="Invalid or expired OTP.")

    if not admin or not admin.otp_hash:
        raise invalid_err

    if _is_expired(admin.otp_expiry):
        admin.otp_hash     = None
        admin.otp_expiry   = None
        admin.otp_attempts = 0
        await db.commit()
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

    if admin.otp_attempts >= OTP_MAX_ATTEMPTS:
        admin.otp_hash     = None
        admin.otp_expiry   = None
        admin.otp_attempts = 0
        await db.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect attempts. Please request a new OTP.",
        )

    if not secrets.compare_digest(admin.otp_hash, _hash_otp(body.otp)):
        admin.otp_attempts += 1
        await db.commit()
        remaining = OTP_MAX_ATTEMPTS - admin.otp_attempts
        raise HTTPException(
            status_code=400,
            detail=f"Incorrect OTP. {remaining} attempt(s) remaining.",
        )

    reset_token = secrets.token_urlsafe(48)

    admin.otp_hash           = None
    admin.otp_expiry         = None
    admin.otp_attempts       = 0
    admin.reset_token        = reset_token
    admin.reset_token_expiry = _utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
    await db.commit()

    return {
        "reset_token": reset_token,
        "message":     "OTP verified. Use the reset_token to set your new password.",
    }


# ── Step 3 — Reset Password ───────────────────────────────────────────────────

async def reset_password(body: ResetPasswordRequest, db: AsyncSession) -> dict:
    result = await db.execute(
        select(Admin).where(Admin.reset_token == body.reset_token)
    )
    admin = result.scalar_one_or_none()

    if not admin:
        raise HTTPException(status_code=400, detail="Invalid reset token.")

    if _is_expired(admin.reset_token_expiry):
        admin.reset_token        = None
        admin.reset_token_expiry = None
        await db.commit()
        raise HTTPException(
            status_code=400,
            detail="Reset token has expired. Please start over.",
        )

    admin.hashed_password    = security.get_password_hash(body.new_password)
    admin.reset_token        = None
    admin.reset_token_expiry = None
    await db.commit()

    return {"message": "Password reset successfully. You can now sign in."}