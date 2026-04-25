from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.app.onboarding.model import Onboarding
from src.app.onboarding.schema import OnboardingCreate
from src.app.user.model import User


async def submit_onboarding(
    body: OnboardingCreate,
    db: AsyncSession,
    current_user: User,
) -> Onboarding:
    result = await db.execute(
        select(Onboarding).where(Onboarding.user_id == current_user.id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User already onboarded")

    onboarding = Onboarding(
        user_id=current_user.id,
        full_name=current_user.full_name,
        email=current_user.email,
        discovery=body.discovery,
        usage=body.usage,
        occupation=body.occupation,
    )
    db.add(onboarding)
    current_user.is_onboarded = True
    await db.commit()
    await db.refresh(onboarding)
    return onboarding


async def get_my_onboarding(
    db: AsyncSession,
    current_user: User,
) -> Onboarding:
    result = await db.execute(
        select(Onboarding).where(Onboarding.user_id == current_user.id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Onboarding not found")
    return record


# ── Admin helper ─────────────────────────────────────────────────────────────
async def get_onboarding_by_user_id(
    user_id: int,
    db: AsyncSession,
) -> Onboarding:
    result = await db.execute(
        select(Onboarding).where(Onboarding.user_id == user_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(
            status_code=404, detail="No onboarding record found for this user"
        )
    return record


 
 
async def get_all_onboarding(db: AsyncSession) -> list:
    result = await db.execute(select(Onboarding))
    return result.scalars().all()
 