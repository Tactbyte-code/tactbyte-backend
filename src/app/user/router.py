from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from src.core.database import session
from src.app.middleware.auth import require_user, require_admin
from src.app.user.model import User
from src.app.user.schema import GoogleSignUp, EmailSignUp, CheckProviderRequest, UserResponse, ForgotPasswordRequest, VerifyOTPRequest, ResetPasswordRequest
from src.app.user.auth import check_provider, google_auth, email_signup, email_login, send_forgot_password_otp, verify_otp, reset_password
from src.app.user import services as user_services
from fastapi.exceptions import HTTPException 
from src.app.admin.model import Admin

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

@router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(session)):
    return await send_forgot_password_otp(body, db)
 
 
@router.post("/auth/verify-otp")
async def verify_otp_route(body: VerifyOTPRequest, db: AsyncSession = Depends(session)):
    return await verify_otp(body, db)
 
 
@router.post("/auth/reset-password")
async def reset_user_password(body: ResetPasswordRequest, db: AsyncSession = Depends(session)):
    return await reset_password(body, db)


@router.get("/auth/me")
async def get_me(current_user: User = Depends(require_user)):
    return {"user": current_user, "message": "User is logged in"}


@router.get("/users")
async def get_users_route(current_admin: Admin = Depends(require_admin)) -> list[UserResponse]:
    return await user_services.get_all_users()


@router.get("/users/count")
async def get_users_count(current_admin: Admin = Depends(require_admin)) -> dict:
    count = await user_services.get_users_count()
    return {"count": count}


@router.get("/users/{user_id}")
async def get_user(user_id: int, current_admin: Admin = Depends(require_admin)) -> UserResponse | None:
    user = await user_services.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user

@router.delete("/users/{user_id}")
async def delete_user(user_id: int, current_admin: Admin = Depends(require_admin)):
    user = await user_services.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    await user_services.delete_user(user_id)
    return {"message": "User deleted successfully"}