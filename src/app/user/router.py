from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.app.user.models.user import User
from models.user_plan import UserPlan
from src.client.user.user import UserResponse, PurchasePlanRequest, UserPlanResponse, UserWithPlanResponse
from src.core.database import session
from middleware.auth import get_current_user
from datetime import datetime, timezone, timedelta
import pytz

router = APIRouter()

IST = pytz.timezone("Asia/Kolkata")

VALID_PLANS = ["basic", "go", "plus", "pro"]
QUERY_COOLDOWN_MINUTES = 30


def build_plan_response(user_plan: UserPlan) -> UserPlanResponse:
    now = datetime.now(IST)

    expires_at = user_plan.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    expires_at = expires_at.astimezone(IST)
    days_left = max((expires_at - now).days, 0)

    last_query_at = user_plan.last_query_at
    can_query = True
    cooldown_minutes_left = 0
    next_query_at = None

    if last_query_at:
        if last_query_at.tzinfo is None:
            last_query_at = last_query_at.replace(tzinfo=timezone.utc)
        last_query_at = last_query_at.astimezone(IST)
        next_query_at = last_query_at + timedelta(minutes=QUERY_COOLDOWN_MINUTES)
        if now < next_query_at:
            can_query = False
            cooldown_minutes_left = int((next_query_at - now).total_seconds() / 60) + 1

    return UserPlanResponse(
        id=user_plan.id,
        user_id=user_plan.user_id,
        plan=user_plan.plan,
        credits_total=user_plan.credits_total,
        credits_used=user_plan.credits_used,
        credits_remaining=user_plan.credits_total - user_plan.credits_used,
        purchased_at=user_plan.purchased_at,
        expires_at=user_plan.expires_at,
        expires_in_days=days_left,
        last_query_at=user_plan.last_query_at,
        next_query_at=next_query_at,
        can_query=can_query,
        cooldown_minutes_left=cooldown_minutes_left,
    )


def build_user_response(user: User, user_plan: UserPlan = None) -> UserWithPlanResponse:
    return UserWithPlanResponse(
        id=user.id,
        firebase_uid=user.firebase_uid,
        full_name=user.full_name,
        email=user.email,
        photo_url=user.photo_url,
        is_onboarded=user.is_onboarded,
        plan=build_plan_response(user_plan) if user_plan else None,
    )


async def get_user_plan(db: AsyncSession, user_id: int) -> UserPlan | None:
    result = await db.execute(select(UserPlan).where(UserPlan.user_id == user_id))
    return result.scalar_one_or_none()


@router.get("/users")
async def get_users(db: AsyncSession = Depends(session)):
    result = await db.execute(select(User))
    return result.scalars().all()


@router.get("/users/me", response_model=UserWithPlanResponse)
async def get_me(
    db: AsyncSession = Depends(session),
    current_user: User = Depends(get_current_user),
):
    user_plan = await get_user_plan(db, current_user.id)
    return build_user_response(current_user, user_plan)


@router.patch("/users/onboard", response_model=UserResponse)
async def complete_onboarding(
    db: AsyncSession = Depends(session),
    current_user: User = Depends(get_current_user),
):
    current_user.is_onboarded = True
    await db.flush()
    return current_user


@router.post("/users/purchase-plan", response_model=UserWithPlanResponse)
async def purchase_plan(
    body: PurchasePlanRequest,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(get_current_user),
):
    plan = body.plan.lower()
    if plan not in VALID_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Choose from: {VALID_PLANS}")

    if body.credits <= 0:
        raise HTTPException(status_code=400, detail="Credits must be greater than 0")

    existing_plan = await get_user_plan(db, current_user.id)

    if existing_plan:
        existing_plan.plan = plan
        existing_plan.credits_total = body.credits
        existing_plan.credits_used = 0
        existing_plan.purchased_at = datetime.now(timezone.utc)
        existing_plan.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        existing_plan.last_query_at = None
        await db.flush()
        user_plan = existing_plan
    else:
        user_plan = UserPlan(
            user_id=current_user.id,
            plan=plan,
            credits_total=body.credits,
            credits_used=0,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(user_plan)
        await db.flush()

    return build_user_response(current_user, user_plan)


@router.post("/users/deduct-credit", response_model=UserWithPlanResponse)
async def deduct_credit(
    db: AsyncSession = Depends(session),
    current_user: User = Depends(get_current_user),
):
    user_plan = await get_user_plan(db, current_user.id)

    if not user_plan:
        raise HTTPException(status_code=402, detail="No active plan found")

    if user_plan.credits_total - user_plan.credits_used <= 0:
        raise HTTPException(status_code=402, detail="Insufficient credits")

    user_plan.credits_used += 1
    await db.flush()

    return build_user_response(current_user, user_plan)