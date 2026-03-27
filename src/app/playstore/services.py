import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.playstore.model import (
    PlaystoreQuery,
    PlaystoreQueryStatus,
    PlaystoreReview,
    PlaystoreSummary,
)
from src.app.user.model import User
from src.app.playstore.schema import PlaystoreQueryInput
from src.infra.runpod.client import trigger as runpod_trigger

logger = logging.getLogger(__name__)


async def create_query(body: PlaystoreQueryInput, db: AsyncSession, current_user: User) -> dict:
    record = PlaystoreQuery(
        user_id=    current_user.id,
        user_email= current_user.email,
        app_id=     body.app_id.strip(),
    )
    db.add(record)
    await db.commit()
    return {"id": str(record.id), "status": record.status, "app_id": record.app_id}


async def get_query(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)
    return {
        "id":             str(record.id),
        "app_id":         record.app_id,
        "app_name":       record.app_name,
        "status":         record.status,
        "failure_reason": record.failure_reason,
        "failed_at_step": record.failed_at_step,
        "created_at":     record.created_at,
        "updated_at":     record.updated_at,
        "fetched_at":     record.fetched_at,
        "summarized_at":  record.summarized_at,
    }


async def list_queries(status: str | None, db: AsyncSession, current_user: User) -> list:
    q = select(
        PlaystoreQuery.id,
        PlaystoreQuery.app_id,
        PlaystoreQuery.app_name,
        PlaystoreQuery.status,
        PlaystoreQuery.failure_reason,
        PlaystoreQuery.failed_at_step,
        PlaystoreQuery.created_at,
        PlaystoreQuery.fetched_at,
        PlaystoreQuery.summarized_at,
    ).where(
        PlaystoreQuery.user_id == current_user.id
    ).order_by(
        PlaystoreQuery.created_at.desc()
    )
    if status:
        q = q.where(PlaystoreQuery.status == status)
    result = await db.execute(q)
    return result.mappings().all()


async def get_all_queries(db: AsyncSession):
    result = await db.execute(select(PlaystoreQuery))
    return result.scalars().all() or []


async def trigger_fetch(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)
    if record.status != PlaystoreQueryStatus.CREATED:
        raise HTTPException(status_code=400, detail=f"Query must be CREATED to fetch. Current: {record.status}")
    job_id = await runpod_trigger(str(query_id), service="playstore", mode="search")
    record.runpod_job_id = job_id
    record.start_step(PlaystoreQueryStatus.FETCHING)
    await db.commit()
    return {"id": str(record.id), "status": record.status, "runpod_job_id": job_id}


async def trigger_summarize(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)
    if record.status != PlaystoreQueryStatus.FETCH_COMPLETE:
        raise HTTPException(status_code=400, detail=f"Query must be FETCH_COMPLETE to summarize. Current: {record.status}")
    job_id = await runpod_trigger(str(query_id), service="playstore", mode="summary")
    record.runpod_job_id = job_id
    record.start_step(PlaystoreQueryStatus.SUMMARIZING)
    await db.commit()
    return {"id": str(record.id), "status": record.status, "runpod_job_id": job_id}


async def get_result(query_id: UUID, db: AsyncSession) -> PlaystoreSummary:
    result = await db.execute(select(PlaystoreSummary).where(PlaystoreSummary.query_id == query_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Result not found")
    return record


async def get_reviews(query_id: UUID, db: AsyncSession) -> dict:
    result = await db.execute(
        select(PlaystoreReview)
        .where(PlaystoreReview.query_id == query_id)
        .order_by(PlaystoreReview.review_created.desc())
    )
    reviews = result.scalars().all()
    return {
        "id":      str(query_id),
        "total":   len(reviews),
        "reviews": [
            {
                "id":             str(r.id),
                "review_id":      r.review_id,
                "username":       r.username,
                "content":        r.content,
                "score":          r.score,
                "thumbs_up":      r.thumbs_up,
                "review_created": r.review_created,
                "reply_content":  r.reply_content,
            }
            for r in reviews
        ],
    }


async def retry_fetch(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)
    allowed = [PlaystoreQueryStatus.FAILED, PlaystoreQueryStatus.FETCH_COMPLETE, PlaystoreQueryStatus.FETCHING]
    if record.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Cannot retry fetch from status: {record.status}")
    await db.execute(delete(PlaystoreReview).where(PlaystoreReview.query_id == query_id))
    record.status         = PlaystoreQueryStatus.CREATED
    record.failure_reason = None
    record.failed_at_step = None
    record.fetched_at     = None
    await db.commit()
    return {"id": str(record.id), "status": record.status}


async def retry_summarize(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)
    allowed = [PlaystoreQueryStatus.FAILED, PlaystoreQueryStatus.COMPLETED, PlaystoreQueryStatus.SUMMARIZING]
    if record.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Cannot retry summarize from status: {record.status}")
    record.status         = PlaystoreQueryStatus.FETCH_COMPLETE
    record.failure_reason = None
    record.failed_at_step = None
    record.summarized_at  = None
    await db.commit()
    return {"id": str(record.id), "status": record.status}


async def _get_query_or_404(query_id: UUID, user_id: int, db: AsyncSession) -> PlaystoreQuery:
    result = await db.execute(
        select(PlaystoreQuery).where(PlaystoreQuery.id == query_id, PlaystoreQuery.user_id == user_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    return record