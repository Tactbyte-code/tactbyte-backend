import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.reddit.model import RedditQuery, QueryStatus, RedditPost, RedditQueryContext, RedditSummary
from src.app.onboarding.model import Onboarding
from src.app.user.model import User
from src.app.reddit.schema import QueryInput, ClarifyingAnswerInput, UpdatePostApproval
from src.app.reddit import intent_service
from src.infra.runpod.client import trigger as runpod_trigger

logger = logging.getLogger(__name__)


async def create_query(body: QueryInput, db: AsyncSession, current_user: User) -> dict:
    result = await db.execute(
        select(Onboarding).where(Onboarding.user_id == current_user.id)
    )
    onboarding = result.scalar_one_or_none()
    profile = {
        "occupation": onboarding.occupation,
        "discovery":  onboarding.discovery,
        "usage":      onboarding.usage,
    } if onboarding else {}

    record = RedditQuery(
        user_id=              current_user.id,
        user_email=           current_user.email,
        query=                body.query,
        profile=              profile,
        clarification_count=  0,
        conversation_history= [],
    )
    db.add(record)
    await db.flush()

    conversation_history = [{"role": "user", "content": body.query}]
    record.conversation_history = conversation_history

    try:
        intent = await intent_service.extract_intent(conversation_history)
    except intent_service.IntentExtractionError as e:
        record.fail_step(str(e.failure_reason))
        await db.commit()
        return {
            "id":             str(record.id),
            "status":         record.status,
            "failure_reason": record.failure_reason,
            "failed_at_step": record.failed_at_step,
        }
        
    if intent.needs_clarification:
        record.start_step(QueryStatus.CLARIFYING)
        record.clarification_count  = 1
        record.conversation_history = conversation_history + [
            {
                "role": "assistant",
                "content": intent.question,
                "options": intent.options,
            }
        ]
        await db.commit()
        return {
            "id":                  str(record.id),
            "status":              record.status,
            "question":            intent.question,
            "options":             intent.options,
            "clarification_count": record.clarification_count,
        }

    record.complete_step(QueryStatus.CLARIFIED)
    await db.commit()
    return {"id": str(record.id), "status": record.status}


async def get_query(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)
    return {
        "id":                   str(record.id),
        "query":                record.query,
        "status":               record.status,
        "failure_reason":       record.failure_reason,
        "failed_at_step":       record.failed_at_step,
        "clarification_count":  record.clarification_count,
        "conversation_history": record.conversation_history,
        "created_at":           record.created_at,
        "updated_at":           record.updated_at,
        "clarified_at":         record.clarified_at,
        "searched_at":          record.searched_at,
        "summarized_at":        record.summarized_at,
    }
    
async def get_all_query(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(RedditQuery, RedditSummary)
        .outerjoin(RedditSummary, RedditSummary.query_id == RedditQuery.id)
        .order_by(RedditQuery.created_at.desc())
    )
    rows = result.all()

    def _fmt(val) -> str | None:
        """Return ISO string whether val is a datetime or already a string."""
        if val is None:
            return None
        return val.isoformat() if hasattr(val, "isoformat") else str(val)

    return [
        {
            "id":                   str(q.id),
            "job_id":               str(q.id),          # frontend uses job_id to open result drawer
            "user_id":              q.user_id,
            "user_email":           q.user_email,
            "query":                q.query,
            "status":               q.status,
            "failure_reason":       q.failure_reason,
            "failed_at_step":       q.failed_at_step,
            "created_at":           _fmt(q.created_at),
            "searched_at":          _fmt(q.searched_at),
            "summarized_at":        _fmt(q.summarized_at),
            # summary fields expected by HistoryItem on the frontend
            "summary_subreddit":    s.subreddit if s else None,
            "summary_analyzed_at":  _fmt(s.analyzed_at) if s else None,
        }
        for q, s in rows
    ]

async def list_queries(status: str | None, db: AsyncSession, current_user: User) -> list[dict]:
    q = select(
        RedditQuery.id,
        RedditQuery.query,
        RedditQuery.status,
        RedditQuery.failure_reason,
        RedditQuery.failed_at_step,
        RedditQuery.created_at,
        RedditQuery.searched_at,
        RedditQuery.summarized_at,
    ).where(
        RedditQuery.user_id == current_user.id
    ).order_by(
        RedditQuery.created_at.desc()
    )
    if status:
        q = q.where(RedditQuery.status == status)
    result = await db.execute(q)
    return result.mappings().all()


async def submit_clarification(
    query_id: UUID, body: ClarifyingAnswerInput, db: AsyncSession, current_user: User
) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != QueryStatus.CLARIFYING:
        raise HTTPException(
            status_code=400,
            detail=f"Query is not in clarifying state. Current status: {record.status}",
        )

    updated_history = record.conversation_history + [
        {"role": "user", "content": body.answer}
    ]
    record.conversation_history = updated_history

    if record.clarification_count >= intent_service.MAX_CLARIFICATION_ROUNDS:
        record.complete_step(QueryStatus.CLARIFIED)
        await db.commit()
        return {"id": str(record.id), "status": record.status}

    try:
        intent = await intent_service.extract_intent(updated_history)
    except intent_service.IntentExtractionError as e:
        record.fail_step(str(e.failure_reason))
        await db.commit()
        return {
            "id":             str(record.id),
            "status":         record.status,
            "failure_reason": record.failure_reason,
            "failed_at_step": record.failed_at_step,
        }

    if intent.needs_clarification:
        record.clarification_count += 1
        record.conversation_history = updated_history + [
            {
                "role": "assistant",
                "content": intent.question,
                "options": intent.options,
            }
        ]
        record.start_step(QueryStatus.CLARIFYING)
        await db.commit()
        return {
            "id":                  str(record.id),
            "status":              record.status,
            "question":            intent.question,
            "options":             intent.options,
            "clarification_count": record.clarification_count,
        }

    record.complete_step(QueryStatus.CLARIFIED)
    await db.commit()
    return {"id": str(record.id), "status": record.status}


async def trigger_search(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != QueryStatus.CLARIFIED:
        raise HTTPException(
            status_code=400,
            detail=f"Query must be CLARIFIED before searching, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="reddit", mode="search")
    record.runpod_job_id = job_id
    record.start_step(QueryStatus.WEB_SEARCHING)
    await db.commit()
    logger.info("Search triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": record.status, "runpod_job_id": job_id}


async def trigger_summarize(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != QueryStatus.SEARCH_COMPLETE:
        raise HTTPException(
            status_code=400,
            detail=f"Query must be SEARCH_COMPLETE before summarizing, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="reddit", mode="summary")
    record.runpod_job_id = job_id
    record.start_step(QueryStatus.SUMMARIZING)
    await db.commit()
    logger.info("Summarize triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": record.status, "runpod_job_id": job_id}


async def get_result(query_id: UUID, db: AsyncSession) -> RedditSummary:
    result = await db.execute(
        select(RedditSummary).where(
            RedditSummary.query_id == query_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Result not found")
    return record


async def retry_search(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    allowed = [QueryStatus.FAILED, QueryStatus.SEARCH_COMPLETE, QueryStatus.WEB_SEARCHING]
    if record.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry search from status: {record.status}",
        )

    await db.execute(delete(RedditPost).where(RedditPost.query_id == query_id))
    await db.execute(delete(RedditQueryContext).where(RedditQueryContext.query_id == query_id))
    record.status         = QueryStatus.CLARIFIED
    record.failure_reason = None
    record.failed_at_step = None
    record.searched_at    = None
    await db.commit()
    logger.info("Search retry initiated", extra={"query_id": str(query_id)})
    return {"id": str(record.id), "status": record.status}


async def retry_summarize(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    allowed = [QueryStatus.FAILED, QueryStatus.COMPLETED, QueryStatus.SUMMARIZING]
    if record.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry summarize from status: {record.status}",
        )

    record.status         = QueryStatus.SEARCH_COMPLETE
    record.failure_reason = None
    record.failed_at_step = None
    record.summarized_at  = None
    await db.commit()
    logger.info("Summarize retry initiated", extra={"query_id": str(query_id)})
    return {"id": str(record.id), "status": record.status}


async def get_posts(query_id: UUID, db: AsyncSession) -> dict:
    result = await db.execute(
        select(RedditPost)
        .where(RedditPost.query_id == query_id)
        .order_by(RedditPost.created_at.asc())
    )
    posts = result.scalars().all()
    return {
        "id":    str(query_id),
        "total": len(posts),
        "posts": [
            {
                "id":            str(p.id),
                "title":         p.title,
                "url":           p.url,
                "snippet":       p.snippet,
                "subreddit":     p.reddit_subreddit,
                "score":         p.reddit_score,
                "num_comments":  p.reddit_num_comments,
                "user_approved": p.user_approved,
            }
            for p in posts
        ],
    }


async def update_post_approval(
    query_id: UUID, post_id: UUID, body: UpdatePostApproval, db: AsyncSession
) -> dict:
    result = await db.execute(
        select(RedditPost).where(
            RedditPost.id       == post_id,
            RedditPost.query_id == query_id,
        )
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if body.user_approved and not post.user_approved:
        count_result = await db.execute(
            select(func.count()).where(
                RedditPost.query_id      == query_id,
                RedditPost.user_approved == True,
                RedditPost.id            != post_id,
            )
        )
        if count_result.scalar() >= 10:
            raise HTTPException(
                status_code=400,
                detail="You can only approve up to 10 posts. Deselect one to approve another.",
            )

    post.user_approved = body.user_approved
    await db.commit()
    return {
        "id":            str(post.id),
        "query_id":      str(post.query_id),
        "title":         post.title,
        "url":           post.url,
        "user_approved": post.user_approved,
    }


# ── Exceptions ────────────────────────────────────────────────────────────────

class RedditPostServiceError(Exception):
    pass

class RedditPostAlreadyExistsError(RedditPostServiceError):
    pass

class RedditPostDatabaseError(RedditPostServiceError):
    pass


# ── Write ─────────────────────────────────────────────────────────────────────

async def bulk_create_reddit_posts(
    db:       AsyncSession,
    query_id: UUID,
    results:  list[dict],
) -> list[RedditPost]:

    if not results:
        raise RedditPostServiceError("results list is empty — nothing to insert.")

    rows: list[RedditPost] = []
    try:
        for item in results:
            if not item.get("url"):
                raise RedditPostServiceError(f"Result missing required field 'url': {item}")
            if not item.get("query"):
                raise RedditPostServiceError(f"Result missing required field 'query': {item}")
            if not item.get("title"):
                raise RedditPostServiceError(f"Result missing required field 'title': {item}")

            row = RedditPost(
                query_id=     query_id,
                search_query= item["query"],
                title=        item["title"],
                url=          item["url"],
                snippet=      item.get("snippet"),
                doc_id=       item.get("doc_id"),
            )
            db.add(row)
            rows.append(row)

        logger.info(
            "bulk_create_reddit_posts staged",
            extra={"query_id": str(query_id), "count": len(rows)},
        )
        return rows

    except RedditPostServiceError:
        raise
    except IntegrityError as e:
        raise RedditPostAlreadyExistsError(
            f"Duplicate query_id + url detected during bulk insert for query {query_id}: {e}"
        ) from e
    except (ValueError, KeyError) as e:
        raise RedditPostDatabaseError(f"Invalid result data: {e}") from e


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_query_or_404(query_id: UUID, user_id: int, db: AsyncSession) -> RedditQuery:
    result = await db.execute(
        select(RedditQuery).where(
            RedditQuery.id      == query_id,
            RedditQuery.user_id == user_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    return record


async def admin_get_result(query_id: UUID, db: AsyncSession) -> RedditSummary:
    """Admin version — no user ownership check."""
    result = await db.execute(
        select(RedditSummary).where(RedditSummary.query_id == query_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Result not found")
    return record


async def admin_get_posts(query_id: UUID, db: AsyncSession) -> dict:
    """Admin version — no user ownership check."""
    result = await db.execute(
        select(RedditPost)
        .where(RedditPost.query_id == query_id)
        .order_by(RedditPost.created_at.asc())
    )
    posts = result.scalars().all()
    return {
        "id":    str(query_id),
        "total": len(posts),
        "posts": [
            {
                "id":            str(p.id),
                "title":         p.title,
                "url":           p.url,
                "snippet":       p.snippet,
                "subreddit":     p.reddit_subreddit,
                "score":         p.reddit_score,
                "num_comments":  p.reddit_num_comments,
                "user_approved": p.user_approved,
            }
            for p in posts
        ],
    }