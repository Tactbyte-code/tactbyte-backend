from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from src.core.database import session
from src.app.middleware.auth import require_user, require_admin
from src.app.user.model import User
from src.app.admin.model import Admin
from src.app.activity.schema import (
    ActivityPing,
    ActivityOut,
    ActivityStatsOut,
    NewUsersOut,
    BackfillOut,
)
from src.app.activity import services as activity_services

router = APIRouter(prefix="/activity", tags=["Activity"])


# ── POST /activity/ping ──────────────────────────────────────────────────────
# ✅ Fixed: user_id is now taken from the auth token, not the payload.
#    This removes the spoofing risk entirely — no need for the id comparison check.
@router.post("/ping", response_model=ActivityOut)
async def ping(
    payload: ActivityPing,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await activity_services.ping_user(
        db,
        current_user.id,          # ✅ always use the authenticated user's id
        payload.action or "active",
    )


# ── POST /activity/ping/admin ────────────────────────────────────────────────
# Admin-only ping — allows the backend/admin to record activity for any user.
@router.post("/ping/admin", response_model=ActivityOut)
async def ping_admin(
    payload: ActivityPing,
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    return await activity_services.ping_user(db, payload.user_id, payload.action or "active")


# ── GET /activity/ ───────────────────────────────────────────────────────────
@router.get("/", response_model=List[ActivityOut])
async def get_all(
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    return await activity_services.get_all_activity(db)


# ── GET /activity/stats ──────────────────────────────────────────────────────
@router.get("/stats", response_model=ActivityStatsOut)
async def get_stats(
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    # ✅ Cast to ActivityStatsOut so Pydantic validates the response shape
    result = await activity_services.get_activity_stats(db)
    return ActivityStatsOut(**result)


# ── GET /activity/new-users ──────────────────────────────────────────────────
@router.get("/new-users", response_model=NewUsersOut)
async def get_new_users(
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    # ✅ Cast to NewUsersOut so Pydantic validates the response shape
    result = await activity_services.get_new_users(db)
    return NewUsersOut(**result)


# ── POST /activity/backfill ──────────────────────────────────────────────────
# Idempotent — safe to call multiple times. Creates missing activity rows.
@router.post("/backfill", response_model=BackfillOut)
async def backfill(
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    return await activity_services.backfill_activity(db)


# ── GET /activity/{user_id} ──────────────────────────────────────────────────
# Must come LAST to avoid catching /stats, /new-users, etc.
@router.get("/{user_id}", response_model=ActivityOut)
async def get_one(
    user_id: int,
    db: AsyncSession = Depends(session),
    current_admin: Admin = Depends(require_admin),
):
    record = await activity_services.get_activity_by_user(db, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="No activity found for this user")
    return record