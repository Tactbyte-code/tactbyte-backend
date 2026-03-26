from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
import pytz

from src.app.plan.model import UserPlan
from src.app.user.model import User

IST = pytz.timezone("Asia/Kolkata")
VALID_PLANS = ["basic", "go", "plus", "pro"]
QUERY_COOLDOWN_MINUTES = 30


async def get_user_plan(db: AsyncSession, user_id: int) -> UserPlan | None:
    result = await db.execute(select(UserPlan).where(UserPlan.user_id == user_id))
    return result.scalar_one_or_none()


async def purchase_plan(user: User, plan_name: str, credits: int, db: AsyncSession) -> UserPlan:
    plan = plan_name.lower()
    if plan not in VALID_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Choose from: {VALID_PLANS}")
    if credits <= 0:
        raise HTTPException(status_code=400, detail="Credits must be greater than 0")

    existing = await get_user_plan(db, user.id)
    now = datetime.now(timezone.utc)

    if existing:
        existing.plan = plan
        existing.credits_total = credits
        existing.credits_used = 0
        existing.purchased_at = now
        existing.expires_at = now + timedelta(days=30)
        existing.last_query_at = None
        await db.flush()
        return existing

    user_plan = UserPlan(
        user_id=user.id,
        plan=plan,
        credits_total=credits,
        credits_used=0,
        expires_at=now + timedelta(days=30),
    )
    db.add(user_plan)
    await db.flush()
    return user_plan


async def deduct_credit(user: User, db: AsyncSession) -> UserPlan:
    user_plan = await get_user_plan(db, user.id)
    if not user_plan:
        raise HTTPException(status_code=402, detail="No active plan found")
    if user_plan.credits_total - user_plan.credits_used <= 0:
        raise HTTPException(status_code=402, detail="Insufficient credits")

    user_plan.credits_used += 1
    await db.flush()
    return user_plan