from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import session
from src.app.middleware.auth import require_user, require_admin
from src.app.user.model import User
from src.app.reddit.schema import QueryInput, ClarifyingAnswerInput, UpdatePostApproval
from src.app.reddit import services

router = APIRouter(prefix="/reddit", tags=["Reddit"])


@router.post("/query", status_code=201)
async def create_query(
    body: QueryInput,
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


@router.post("/query/{query_id}/clarify")
async def submit_clarification(
    query_id: UUID,
    body: ClarifyingAnswerInput,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.submit_clarification(query_id, body, db, current_user)


@router.post("/query/{query_id}/search")
async def trigger_search(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.trigger_search(query_id, db, current_user)


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


@router.post("/query/{query_id}/retry-search")
async def retry_search(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.retry_search(query_id, db, current_user)


@router.post("/query/{query_id}/retry-summarize")
async def retry_summarize(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.retry_summarize(query_id, db, current_user)


@router.get("/query/{query_id}/posts")
async def get_posts(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.get_posts(query_id, db)


@router.patch("/query/{query_id}/posts/{post_id}")
async def update_post_approval(
    query_id: UUID,
    post_id: UUID,
    body: UpdatePostApproval,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.update_post_approval(query_id, post_id, body, db)

