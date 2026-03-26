from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
import pytz
from src.core.database import session
from src.app.middleware.auth import require_user
from src.app.user.model import User
from src.app.plan.model import UserPlan
from src.app.plan import services as plan_services
from src.app.plan.schema import PurchasePlanRequest, UserPlanResponse, UserWithPlanResponse

router = APIRouter(tags=["Plan"])

IST = pytz.timezone("Asia/Kolkata")
QUERY_COOLDOWN_MINUTES = 30


# ── Helpers ─────────────────────────────────────────────────────────────────

def build_plan_response(user_plan: UserPlan) -> UserPlanResponse:
    from datetime import timezone
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


def build_user_response(user: User, user_plan: UserPlan | None = None) -> UserWithPlanResponse:
    return UserWithPlanResponse(
        id=user.id,
        firebase_uid=user.firebase_uid,
        full_name=user.full_name,
        email=user.email,
        photo_url=user.photo_url,
        is_onboarded=user.is_onboarded,
        plan=build_plan_response(user_plan) if user_plan else None,
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/users/purchase-plan", response_model=UserWithPlanResponse)
async def purchase_plan(
    body: PurchasePlanRequest,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    user_plan = await plan_services.purchase_plan(current_user, body.plan, body.credits, db)
    return build_user_response(current_user, user_plan)


@router.post("/users/deduct-credit", response_model=UserWithPlanResponse)
async def deduct_credit(
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    user_plan = await plan_services.deduct_credit(current_user, db)
    return build_user_response(current_user, user_plan)