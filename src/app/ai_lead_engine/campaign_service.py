# src/app/ai_lead_engine/campaign_service.py

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from src.app.ai_lead_engine.model import Campaign, CampaignHistory, Keyword
from src.app.ai_lead_engine.schema import CreateCampaignBody, UpdateCampaignBody
from src.app.user.model import User
from datetime import datetime, timezone


async def get_campaigns(db: AsyncSession, user: User) -> list[Campaign]:
    result = await db.execute(
        select(Campaign).where(Campaign.user_id == user.id).order_by(Campaign.created_at.desc())
    )
    return result.scalars().all()


async def get_campaign(db: AsyncSession, user: User, campaign_id: int) -> Campaign:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


async def create_campaign(db: AsyncSession, user: User, body: CreateCampaignBody) -> Campaign:
    campaign = Campaign(
        user_id=user.id,
        name=body.name,
        description=body.description,
        intent=body.intent,
        prompt=body.prompt,
        website=body.website,
    )
    db.add(campaign)
    await db.flush()
    
    for kw in body.keywords or []:
        keyword = Keyword(
            keyword=kw.keyword,
            match_type=kw.match_type,
            campaign_id=campaign.id,
        )
        db.add(keyword)

    # Record creation in history
    history = CampaignHistory(
        campaign_id=campaign.id,
        action="created",
        snapshot=_campaign_snapshot(campaign),
    )
    db.add(history)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def update_campaign(db: AsyncSession, user: User, campaign_id: int, body: UpdateCampaignBody) -> Campaign:
    campaign = await get_campaign(db, user, campaign_id)

    old_snapshot = _campaign_snapshot(campaign)
    changed_fields = {}

    update_data = body.model_dump(exclude_unset=True)
    for field, new_value in update_data.items():
        old_value = getattr(campaign, field)
        if old_value != new_value:
            changed_fields[field] = {"old": old_value, "new": new_value}
            setattr(campaign, field, new_value)

    if not changed_fields:
        return campaign

    history = CampaignHistory(
        campaign_id=campaign.id,
        action="updated",
        snapshot=old_snapshot,
        changed_fields=changed_fields,
    )
    db.add(history)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def delete_campaign(db: AsyncSession, user: User, campaign_id: int) -> None:
    campaign = await get_campaign(db, user, campaign_id)

    # Record deletion before deleting (cascade will wipe history too)
    history = CampaignHistory(
        campaign_id=campaign.id,
        action="deleted",
        snapshot=_campaign_snapshot(campaign),
    )
    db.add(history)
    await db.flush()

    await db.delete(campaign)
    await db.commit()


async def get_history(db: AsyncSession, user: User, campaign_id: int) -> list[CampaignHistory]:
    await get_campaign(db, user, campaign_id)  # ownership check
    result = await db.execute(
        select(CampaignHistory)
        .where(CampaignHistory.campaign_id == campaign_id)
        .order_by(CampaignHistory.created_at.desc())
    )
    return result.scalars().all()


async def get_history_entry(db: AsyncSession, user: User, campaign_id: int, history_id: int) -> CampaignHistory:
    await get_campaign(db, user, campaign_id)  # ownership check
    result = await db.execute(
        select(CampaignHistory).where(
            CampaignHistory.id == history_id,
            CampaignHistory.campaign_id == campaign_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History entry not found")
    return entry


def _campaign_snapshot(campaign: Campaign) -> dict:
    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "intent": campaign.intent,
        "prompt": campaign.prompt,
        "website": campaign.website,
    }