from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.app.user.models.user import User
from src.client.user.user import GoogleSignUp, EmailSignUp, UserResponse, SessionResponse
from src.core.database import session
from middleware.auth import get_current_user
from pydantic import BaseModel
import bcrypt

router = APIRouter()


class CheckProviderRequest(BaseModel):
    email: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


@router.post("/auth/check-provider")
async def check_provider(body: CheckProviderRequest, db: AsyncSession = Depends(session)):
    user = await get_user_by_email(db, body.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    provider = "google" if user.hashed_password is None else "email"
    return {"provider": provider}


@router.post("/auth/google", response_model=UserResponse)
async def google_auth(body: GoogleSignUp, db: AsyncSession = Depends(session)):
    user = await get_user_by_email(db, body.email)
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


@router.post("/auth/email-signup", response_model=UserResponse)
async def email_sign_up(body: EmailSignUp, db: AsyncSession = Depends(session)):
    user = await get_user_by_email(db, body.email)
    if user:
        return user

    user = User(
        firebase_uid=body.firebase_uid,
        full_name=body.full_name,
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    return user


@router.post("/auth/email-login")
async def email_login(body: EmailSignUp, db: AsyncSession = Depends(session)):
    user = await get_user_by_email(db, body.email)
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


@router.get("/auth/me", response_model=SessionResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "user": current_user,
        "message": "User is logged in",
    }