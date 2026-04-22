from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import session
from src.app.middleware.auth import require_user, require_admin
from src.app.user.model import User
from src.app.onboarding.schema import OnboardingCreate
from src.app.onboarding.services import (
    submit_onboarding,
    get_my_onboarding,
    get_onboarding_by_user_id,
)

router = APIRouter(tags=["Onboarding"])

@router.post("/onboarding")
async def submit_onboarding_route(
    body: OnboardingCreate,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await submit_onboarding(body, db, current_user)


@router.get("/onboarding/me")
async def get_my_onboarding_route(
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await get_my_onboarding(db, current_user)

@router.get("/admin/onboarding/{user_id}")
async def get_user_onboarding_admin(
    user_id: int,
    db: AsyncSession = Depends(session),
    _admin=Depends(require_admin),
):
    return await get_onboarding_by_user_id(user_id, db)