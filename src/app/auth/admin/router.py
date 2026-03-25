from fastapi import APIRouter, Depends, HTTPException
from src.app.auth.admin.schema import AdminLoginForm
from src.core.database import session
from src.app.admin.model import Admin
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core import security

router = APIRouter(tags=["Auth", "Admin"])

@router.post("/login")
async def admin_login(
    body: AdminLoginForm,
    session: AsyncSession = Depends(session)
):

    result = await session.execute(
        select(Admin).where(
            Admin.email == body.email,
        )
    )
    
    admin = result.scalar_one_or_none()

    if not admin or not security.verify_password(body.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if admin.session_token is not None:
        raise HTTPException(status_code=403, detail="Already logged in from another session")


    session.commit()

    access_token  = security.authX.create_access_token(uid=str(admin.id))
    refresh_token = security.authX.create_refresh_token(uid=str(admin.id))

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "admin": {
            "email":     admin.email,
            "full_name": admin.name,
            "role":      admin.role,
            "permissions": admin.permissions,
        },
    }


@router.post("/logout")
def admin_logout():
    # todo in any state is stored in db
    return {"message": "Logged out successfully"}


@router.post("/refresh")
def refresh_access_token(token=Depends(security.authX.refresh_token_required)):
    return {"access_token": security.authX.create_access_token(uid=token.sub)}

