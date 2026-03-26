from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import session
from src.core.security import authX
from src.app.admin.schema import AdminLoginForm, AdminCreate
from src.app.admin.auth import login, logout, refresh
from src.app.middleware.auth import require_admin
from src.app.admin.model import Admin, AdminRole
from src.app.admin import services as admin_services

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


@router.get("/admins")
async def list_admins(
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    return await admin_services.get_all_admins(db)

@router.post("/admins")
async def create_admin(
    body: AdminCreate,
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    return await admin_services.create_admin(body, db)

@router.patch("/admins/{admin_id}/role")
async def assign_role(
    admin_id: int,
    role: AdminRole,
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    return await admin_services.assign_role(admin_id, role, current_admin, db)

@router.delete("/admins/{admin_id}", status_code=204)
async def delete_admin(
    admin_id: int,
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    await admin_services.delete_admin(admin_id, current_admin, db)