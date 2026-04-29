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
from src.app.ai_lead_engine.keyword_service import get_keywords
from src.infra.runpod.client import trigger as runpod_trigger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def get_leads(
    db: AsyncSession,
    user,
    campaign_id: int,
    filters,
) -> list[Lead]:

    campaign = await get_campaign(db, user, campaign_id)

    query = (
        select(Lead)
        .where(Lead.campaign_id == campaign_id)
        .options(selectinload(Lead.post))  # eager load post
    )

    if filters.min_score is not None:
        query = query.where(Lead.ai_score >= filters.min_score)

    if filters.history_id is not None:
        query = query.where(Lead.campaign_history_id == filters.history_id)

    query = query.where(Lead.status != "ignored")

    query = query.order_by(Lead.ai_score.desc(), Lead.created_at.desc())

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


async def trigger_sync_leads(
    campaign_id: int,
    db: AsyncSession,
    current_user: User,
):

    campaign = await get_campaign(db, current_user, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    keywords = await get_keywords(db, current_user, campaign_id)
    keyword_strings = [k.keyword for k in keywords if k.keyword]

    if not keyword_strings:
        raise HTTPException(status_code=400, detail="No keywords on campaign")


    history = CampaignHistory(campaign_id=campaign_id, action="created")
    db.add(history)
    await db.flush()

    job_id = await runpod_trigger(str(history.id), service="ai-lead-engine", mode="sync-leads")

    history.runpod_job_id  = job_id

    await db.commit()

    print(f"Lead sync triggered campaign_id={campaign.id}, campaign_history_id={history.id}, runpod_job_id={job_id}")
    
    return {
        "campaign_id":   campaign_id,
        "campaign_history_id": history.id,
        "status":        history.action,
        "runpod_job_id": job_id,
    }