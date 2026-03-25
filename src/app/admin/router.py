from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import session
from src.core.security import authX
from src.app.admin.schema import AdminLoginForm
from src.app.admin.auth import login, logout, refresh

router = APIRouter(tags=["Admin Auth"])


@router.post("/login")
async def admin_login(
    body: AdminLoginForm,
    db: AsyncSession = Depends(session),
):
    return await login(body, db)


@router.post("/logout")
async def admin_logout():
    return await logout()


@router.post("/refresh")
async def refresh_access_token(
    token=Depends(authX.refresh_token_required),
):
    return await refresh(token)