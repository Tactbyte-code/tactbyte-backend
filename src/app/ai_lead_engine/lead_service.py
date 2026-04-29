# src/app/ai_lead_engine/lead_service.py

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from src.app.ai_lead_engine.model import Lead, LeadPost, CampaignHistory
from src.app.ai_lead_engine.schema import LeadFilterParams
from src.app.ai_lead_engine.campaign_service import get_campaign
from src.app.user.model import User
import aiohttp
from urllib.parse import quote
from sqlalchemy.dialects.postgresql import insert
from src.app.ai_lead_engine.keyword_service import get_keywords
import uuid
from datetime import datetime, timezone
import asyncio

BASE_URL = "https://www.reddit.com/search.json"
HEADERS = {"User-Agent": "tactbyte-vps leadbot/1.2"}

async def get_leads(
    db: AsyncSession,
    user: User,
    campaign_id: int,
    filters: LeadFilterParams,
) -> list[Lead]:
    await get_campaign(db, user, campaign_id)  # ownership check

    query = (
        select(Lead)
        .where(Lead.campaign_id == campaign_id)
        .options(selectinload(Lead.post))   # eager load post in one query
        .order_by(Lead.created_at.desc())
    )

    if filters.status:
        query = query.where(Lead.status == filters.status)
    if filters.category:
        query = query.where(Lead.category == filters.category)
    if filters.platform:
        query = query.where(Lead.platform == filters.platform)
    if filters.min_score is not None:
        query = query.where(Lead.ai_score >= filters.min_score)
    if filters.history_id is not None:
        query = query.where(Lead.campaign_history_id == filters.history_id)

    result = await db.execute(query)
    return result.scalars().all()


async def get_lead(db: AsyncSession, user: User, campaign_id: int, lead_id: str) -> Lead:
    await get_campaign(db, user, campaign_id)  # ownership check

    result = await db.execute(
        select(Lead)
        .where(Lead.id == UUID(lead_id), Lead.campaign_id == campaign_id)
        .options(selectinload(Lead.post), selectinload(Lead.actions))
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return lead


async def update_status(
    db: AsyncSession,
    user: User,
    campaign_id: int,
    lead_id: str,
    new_status: str,
) -> Lead:
    valid_statuses = {"new", "replied", "ignored", "converted"}
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {valid_statuses}",
        )

    lead = await get_lead(db, user, campaign_id, lead_id)
    lead.status = new_status
    await db.commit()
    await db.refresh(lead)
    return lead


async def get_similar(
    db: AsyncSession,
    user: User,
    campaign_id: int,
    lead_id: str,
    limit: int = 10,
    threshold: float = 0.5,
) -> list[dict]:
    lead = await get_lead(db, user, campaign_id, lead_id)

    if lead.embedding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This lead has no embedding yet",
        )

    # pgvector cosine similarity — returns other leads in same campaign
    from sqlalchemy import text
    result = await db.execute(text("""
        SELECT
            l.id,
            l.status,
            l.ai_score,
            l.category,
            l.platform,
            l.search_keyword,
            lp.title,
            lp.url,
            1 - (l.embedding <=> :vec) AS similarity
        FROM leads l
        LEFT JOIN lead_posts lp ON lp.lead_id = l.id
        WHERE l.campaign_id = :campaign_id
          AND l.id != :lead_id
          AND l.embedding IS NOT NULL
          AND 1 - (l.embedding <=> :vec) >= :threshold
        ORDER BY l.embedding <=> :vec
        LIMIT :limit
    """), {
        "vec": str(lead.embedding),
        "campaign_id": campaign_id,
        "lead_id": str(lead.id),
        "threshold": threshold,
        "limit": limit,
    })

    rows = result.fetchall()
    return [dict(row._mapping) for row in rows]



async def _fetch_reddit(session, query: str):
    url = f"{BASE_URL}?q={query}&sort=new&t=week&limit=50&type=posts"

    async with session.get(url, headers=HEADERS) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data["data"]["children"]

async def fetch_and_store_reddit_leads(db, user, campaign_id: int):
    campaign = await get_campaign(db, user, campaign_id)
    if not campaign:
        raise ValueError("Campaign not found")

    keywords = await get_keywords(db, user, campaign_id)
    keyword_strings = [k.keyword for k in keywords if k.keyword]

    if not keyword_strings:
        return 0

    history = CampaignHistory(
        campaign_id=campaign_id,
        action="fetch"
    )
    db.add(history)
    await db.flush()

    seen = set()
    lead_rows = []
    post_rows = []

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_reddit(session, q) for q in keyword_strings]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

    for query, results in zip(keyword_strings, results_list):
        if isinstance(results, Exception) or not results:
            continue

        for item in results:
            p = item.get("data")
            if not p:
                continue

            post_id = p.get("id")
            if not post_id or post_id in seen:
                continue

            seen.add(post_id)
            lead_uuid = uuid.uuid4()

            lead_rows.append({
                "id": lead_uuid,
                "campaign_id": campaign_id,
                "campaign_history_id": history.id,
                "platform": "reddit",
                "status": "new",
                "search_keyword": query,
            })

            post_rows.append({
                "id": uuid.uuid4(),
                "lead_id": lead_uuid,
                "external_id": post_id,
                "title": p.get("title"),
                "content": p.get("selftext"),
                "author": p.get("author"),
                "url": "https://reddit.com" + p.get("permalink", ""),
                "likes": p.get("ups"),
                "comments_count": p.get("num_comments"),
                "post_created_at": datetime.fromtimestamp(
                    p["created_utc"], tz=timezone.utc
                ) if p.get("created_utc") else None,
                "subreddit": p.get("subreddit"),
                "subreddit_id": p.get("subreddit_id"),
                "fetch_ok": True,
                "fetched_at": datetime.now(timezone.utc),
            })

    if not lead_rows:
        return 0

    await db.execute(
        insert(Lead).values(lead_rows).on_conflict_do_nothing(index_elements=["id"])
    )
    await db.execute(
        insert(LeadPost).values(post_rows).on_conflict_do_nothing(index_elements=["id"])
    )

    history.snapshot = {
        "keywords": keyword_strings,
        "total_leads": len(lead_rows),
    }

    await db.commit()

    return len(lead_rows)