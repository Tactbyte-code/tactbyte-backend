# src/app/seeder.py
import asyncio
from src.app.admin.seeder import seed_admin

async def run_all():
    await seed_admin()


if __name__ == "__main__":
    asyncio.run(run_all())