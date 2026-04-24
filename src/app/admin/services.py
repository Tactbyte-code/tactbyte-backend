from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core import security
from src.app.admin.model import Admin, AdminRole
from src.app.admin.schema import AdminCreate
from src.app.utils.send_admin_credentials import send_admin_credentials


# ─── Get all admins ────────────────────────────────────────────────────────────

async def get_all_admins(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(Admin))
    admins = result.scalars().all()
    return [
        {
            "id":          a.id,
            "name":        a.name,
            "email":       a.email,
            "role":        a.role,
            "permissions": a.permissions,
        }
        for a in admins
    ]


# ─── Create admin ──────────────────────────────────────────────────────────────

async def create_admin(body: AdminCreate, db: AsyncSession) -> dict:
    # 1. Duplicate email guard
    existing = await db.execute(select(Admin).where(Admin.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An admin with this email already exists.")

    # 2. Hash password
    
    hashed = security.get_password_hash(body.password)
    # 3. Persist
    new_admin = Admin(
        name            = body.name,
        email           = body.email,
        hashed_password = hashed,
        role            = body.role,
        permissions     = body.permissions,
    )
    db.add(new_admin)
    await db.commit()
    await db.refresh(new_admin)

    # 4. Send credentials email — capture success/failure for the response
    email_sent = False
    try:
        send_admin_credentials(
            to_email  = body.email,
            full_name = body.name,
            password  = body.password,
            role      = body.role,
        )
        email_sent = True
    except Exception as mail_err:
        print(f"⚠️  Admin created but credential email failed: {mail_err}")

    return {
        "id":         new_admin.id,
        "name":       new_admin.name,
        "email":      new_admin.email,
        "role":       new_admin.role,
        "email_sent": email_sent,          # ← frontend reads this
        "message":    (
            "Admin created successfully. Credentials sent to their email."
            if email_sent else
            "Admin created. (Email delivery failed — check SMTP config.)"
        ),
    }


# ─── Assign role ───────────────────────────────────────────────────────────────

async def assign_role(
    admin_id: int,
    role: AdminRole,
    current_admin: Admin,
    db: AsyncSession,
) -> dict:
    if current_admin.role != AdminRole.super_admin:
        raise HTTPException(status_code=403, detail="Only super admins can assign roles.")

    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    admin  = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found.")

    admin.role = role
    await db.commit()
    await db.refresh(admin)
    return {"id": admin.id, "role": admin.role, "message": "Role updated successfully."}


# ─── Delete admin ──────────────────────────────────────────────────────────────

async def delete_admin(admin_id: int, current_admin: Admin, db: AsyncSession) -> None:
    if current_admin.id == admin_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    admin  = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found.")

    await db.delete(admin)
    await db.commit()