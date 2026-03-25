from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash, verify_password
from src.app.user.model import User
from src.app.user.schema import GoogleSignUp, EmailSignUp, CheckProviderRequest
from src.app.user.services import get_user_by_email


async def check_provider(body: CheckProviderRequest, db: AsyncSession) -> dict:
    user = await get_user_by_email(body.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    provider = "google" if user.hashed_password is None else "email"
    return {"provider": provider}


async def google_auth(body: GoogleSignUp, db: AsyncSession) -> User:
    user = await get_user_by_email(body.email)
    if user:
        return user

    user = User(
        firebase_uid=body.firebase_uid,
        full_name=body.full_name,
        email=body.email,
        photo_url=body.photo_url,
        hashed_password=None,
    )
    db.add(user)
    await db.flush()
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

    return user