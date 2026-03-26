from sqlalchemy import select, func
from src.core.database import AsyncSessionLocal
from src.app.user.model import User


async def get_all_users() -> list[User] | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User)
        )
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
        result = await session.execute(
            select(func.count(User.id))
        )
        return result.scalar()