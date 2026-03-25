from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import session
from src.app.middleware.auth import require_user
from src.app.user.model import User
from src.app.user.schema import GoogleSignUp, EmailSignUp, CheckProviderRequest
from src.app.user.auth import check_provider, google_auth, email_signup, email_login

router = APIRouter(tags=["User Auth"])


@router.post("/auth/check-provider")
async def check_provider_route(
    body: CheckProviderRequest,
    db: AsyncSession = Depends(session),
):
    return await check_provider(body, db)


@router.post("/auth/google")
async def google_auth_route(
    body: GoogleSignUp,
    db: AsyncSession = Depends(session),
):
    return await google_auth(body, db)


@router.post("/auth/email-signup")
async def email_signup_route(
    body: EmailSignUp,
    db: AsyncSession = Depends(session),
):
    return await email_signup(body, db)


@router.post("/auth/email-login")
async def email_login_route(
    body: EmailSignUp,
    db: AsyncSession = Depends(session),
):
    return await email_login(body, db)


@router.get("/auth/me")
async def get_me(current_user: User = Depends(require_user)):
    return {"user": current_user, "message": "User is logged in"}