from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from src.core.database import session
from src.app.middleware.auth import require_user, require_admin
from src.app.reddit import services
from sqlalchemy import select

router = APIRouter(prefix="/reddit", tags=["Reddit"])

@router.get("/queries")
async def get_queries(
    db: AsyncSession = Depends(session),
    current_user = Depends(require_admin),
):
    return await services.get_all_query(db)


# @router.get("/admin/queries")
# async def get_queries(
#     db: AsyncSession = Depends(session),
#     current_user = Depends(require_admin),
# ):
#     return await services.get_all_query(db)


@router.get("/query/{query_id}/result")
async def admin_get_result(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user=Depends(require_admin),
):
    return await services.admin_get_result(query_id, db)


@router.get("/query/{query_id}/posts")
async def admin_get_posts(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user=Depends(require_admin),
):
    return await services.admin_get_posts(query_id, db)