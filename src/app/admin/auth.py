from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core import security
from src.app.admin.model import Admin
from src.app.admin.schema import AdminLoginForm


async def login(body: AdminLoginForm, db: AsyncSession) -> dict:
    result = await db.execute(
        select(Admin).where(Admin.email == body.email)
    )
    admin = result.scalar_one_or_none()

    if not admin or not security.verify_password(body.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # if admin.session_token is not None:
    #     raise HTTPException(status_code=403, detail="Already logged in from another session")

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


async def logout() -> dict:
    # todo: clear session_token from db
    return {"message": "Logged out successfully"}


async def refresh(token) -> dict:
    return {
        "access_token": security.authX.create_access_token(uid=token.sub)
    }