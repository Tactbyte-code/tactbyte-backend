from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from src.app.admin.model import Admin, AdminRole
from src.app.admin.schema import AdminCreate
from src.core.security import get_password_hash

async def get_all_admins(db: AsyncSession) -> list[Admin]:
    result = await db.execute(select(Admin).order_by(Admin.id))
    return result.scalars().all() or []

async def create_admin(body: AdminCreate, db: AsyncSession) -> Admin:
    email_clean = body.email.lower().strip()
    result = await db.execute(select(Admin).where(Admin.email == email_clean))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_admin = Admin(
        name=body.name,
        email=email_clean,
        hashed_password=get_password_hash(body.password),
        role=body.role,
        permissions=body.permissions,
    )
    db.add(new_admin)
    await db.commit()
    await db.refresh(new_admin)
    return new_admin

async def assign_role(admin_id: int, role: AdminRole, caller: Admin, db: AsyncSession) -> Admin:
    if caller.id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Admin not found")
    target.role = role
    await db.commit()
    await db.refresh(target)
    return target

async def delete_admin(admin_id: int, current_admin: Admin, db: AsyncSession) -> None:
    if current_admin.id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Admin not found")
    await db.delete(target)
    await db.commit()