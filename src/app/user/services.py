from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.app.user.model import User


async def get_user_by_email(email: str) -> User | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()