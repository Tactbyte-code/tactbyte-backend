from asyncio import get_event_loop
from functools import partial

from authx import TokenPayload
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.database import session
from src.core.security import authX
from src.app.user.model import User
from src.app.admin.model import Admin

security = HTTPBearer()

async def verify_firebase_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    token = credentials.credentials
    try:
        loop = get_event_loop()
        decoded = await loop.run_in_executor(
            None, partial(auth.verify_id_token, token)
        )
        return decoded
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
        )


async def require_user(
    decoded: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(session),
) -> User:
    uid = decoded.get("uid")
    result = await db.execute(
        select(User).where(User.firebase_uid == uid)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


async def require_admin(
    payload: TokenPayload = Depends(authX.access_token_required),
    db: AsyncSession = Depends(session),
) -> Admin:
    result = await db.execute(
        select(Admin).where(Admin.id == int(payload.sub))
    )
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )
    return admin


async def require_any(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(session),
) -> User | Admin:
    token = credentials.credentials

    # try Firebase (user) first
    try:
        loop = get_event_loop()
        decoded = await loop.run_in_executor(
            None, partial(auth.verify_id_token, token)
        )
        uid = decoded.get("uid")
        result = await db.execute(
            select(User).where(User.firebase_uid == uid)
        )
        user = result.scalar_one_or_none()
        if user:
            return user
    except Exception:
        pass

    # fall back to admin JWT
    try:
        payload = authX.verify_token(token, type="access")
        result = await db.execute(
            select(Admin).where(Admin.id == int(payload.sub))
        )
        admin = result.scalar_one_or_none()
        if admin:
            return admin
    except Exception:
        pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )