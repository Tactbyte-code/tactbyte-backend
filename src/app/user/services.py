from sqlalchemy import select, func
from src.core.database import AsyncSessionLocal
from src.app.user.model import User


async def get_all_users() -> list[User]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        return result.scalars().all() or []


async def get_user_by_email(email: str) -> User | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: int) -> User | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()


async def get_users_count() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.count(User.id)))
        return result.scalar()


async def toggle_user_active(user_id: int) -> User | None:
    """Flip is_active on a user. Returns the updated User, or None if not found."""
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if not user:
            return None
        user.is_active = not user.is_active
        await db.commit()
        await db.refresh(user)
        return user