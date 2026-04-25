from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from src.core.database import session
from src.app.middleware.auth import require_admin
from src.app.playstore import services

router = APIRouter(
prefix="/playstore",
    tags=["Playstore Admin"]
)

@router.get("/queries")
async def get_all_queries(
    db: AsyncSession = Depends(session),
    current_user=Depends(require_admin),
):
    print('hello')
    return await services.get_all_queries(db)

@router.get("/query/{job_id}/result")
async def get_query_result(
    job_id: UUID,
    db: AsyncSession = Depends(session),
    current_user=Depends(require_admin),
):
    return await services.get_result(job_id, db)

@router.get("/query/{job_id}/posts")
async def get_query_posts(
    job_id: UUID,
    db: AsyncSession = Depends(session),
    current_user=Depends(require_admin),
):
    return await services.get_reviews(job_id, db)