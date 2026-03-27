from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import session
from src.app.middleware.auth import require_user, require_admin
from src.app.user.model import User
from src.app.playstore.schema import PlaystoreQueryInput
from src.app.playstore import services

router = APIRouter(prefix="/playstore", tags=["Playstore"])


@router.post("/query", status_code=201)
async def create_query(
    body: PlaystoreQueryInput,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.create_query(body, db, current_user)


@router.get("/queries")
async def list_queries(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.list_queries(status, db, current_user)


@router.get("/query/{query_id}")
async def get_query(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.get_query(query_id, db, current_user)


@router.get("/query/{query_id}/status")
async def get_query_status(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.get_query(query_id, db, current_user)


@router.post("/query/{query_id}/fetch")
async def trigger_fetch(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.trigger_fetch(query_id, db, current_user)


@router.post("/query/{query_id}/summarize")
async def trigger_summarize(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.trigger_summarize(query_id, db, current_user)


@router.get("/query/{query_id}/result")
async def get_result(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.get_result(query_id, db)


@router.get("/query/{query_id}/reviews")
async def get_reviews(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.get_reviews(query_id, db)



@router.post("/query/{query_id}/retry-fetch")
async def retry_fetch(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.retry_fetch(query_id, db, current_user)


@router.post("/query/{query_id}/retry-summarize")
async def retry_summarize(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.retry_summarize(query_id, db, current_user)


@router.get("/admin/queries")
async def get_all_queries(
    db: AsyncSession = Depends(session),
    current_user=Depends(require_admin),
):
    return await services.get_all_queries(db)