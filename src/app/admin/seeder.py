# src/app/admin/seeder.py

import asyncio
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.core.settings import settings
from src.core.security import get_password_hash
from src.app.admin.model import Admin, AdminRole


async def seed_admin():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Admin).where(Admin.email == settings.ADMIN_EMAIL)
        )
        existing = result.scalar_one_or_none()

        if existing:
            print(f"[seeder] Admin already exists: {settings.ADMIN_EMAIL}")
            return

        admin = Admin(
            name=settings.ADMIN_NAME,
            email=settings.ADMIN_EMAIL,
            hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
            role=AdminRole.super_admin,
            permissions={},
        )

        session.add(admin)
        await session.commit()
        print(f"[seeder] Admin created: {settings.ADMIN_EMAIL}")