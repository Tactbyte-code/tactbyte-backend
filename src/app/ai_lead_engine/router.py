from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.ai_lead_engine import lead_service
from src.core.database import session
from src.app.middleware.auth import require_user
from src.app.user.model import User
from src.app.ai_lead_engine import (
    keyword_service,
    campaign_service,
    lead_service,
    action_service,
)
from src.app.ai_lead_engine.schema import (
    # Campaign
    CreateCampaignBody,
    UpdateCampaignBody,
    # Keywords
    GenerateKeywordsBody,
    CreateKeywordBody,
    # Leads
    LeadFilterParams,
    # Actions
    CreateLeadActionBody,
)

router = APIRouter(prefix="/ai-lead-engine", tags=["Leads"])


# ── Campaigns ──────────────────────────────────────────────────────────────────

@router.get("/campaigns")
async def get_campaigns(
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await campaign_service.get_campaigns(db, current_user)


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CreateCampaignBody,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await campaign_service.create_campaign(db, current_user, body)


@router.get("/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await campaign_service.get_campaign(db, current_user, campaign_id)


@router.patch("/campaigns/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    body: UpdateCampaignBody,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await campaign_service.update_campaign(db, current_user, campaign_id, body)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await campaign_service.delete_campaign(db, current_user, campaign_id)


# ── Campaign History ───────────────────────────────────────────────────────────

@router.get("/campaigns/{campaign_id}/history")
async def get_campaign_history(
    campaign_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await campaign_service.get_history(db, current_user, campaign_id)


@router.get("/campaigns/{campaign_id}/history/{history_id}")
async def get_campaign_history_entry(
    campaign_id: int,
    history_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await campaign_service.get_history_entry(db, current_user, campaign_id, history_id)


# ── Keywords ───────────────────────────────────────────────────────────────────

@router.get("/campaigns/{campaign_id}/keywords")
async def get_keywords(
    campaign_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await keyword_service.get_keywords(db, current_user, campaign_id)


@router.post("/campaigns/{campaign_id}/keywords", status_code=status.HTTP_201_CREATED)
async def create_keyword(
    campaign_id: int,
    body: CreateKeywordBody,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await keyword_service.create_keyword(db, current_user, campaign_id, body)


@router.delete("/campaigns/{campaign_id}/keywords/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyword(
    campaign_id: int,
    keyword_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await keyword_service.delete_keyword(db, current_user, campaign_id, keyword_id)


@router.post("/generate-keywords")
async def generate_keywords(
    body: GenerateKeywordsBody,
    current_user: User = Depends(require_user),
):
    
    return await keyword_service.generate_keywords(body)


# ── Leads ──────────────────────────────────────────────────────────────────────

@router.get("/campaigns/{campaign_id}/leads")
async def get_leads(
    campaign_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
    status: str | None = None,         # ?status=new
    category: str | None = None,       # ?category=hiring_outsourcing
    platform: str | None = None,       # ?platform=reddit
    min_score: int | None = None,      # ?min_score=8
    history_id: int | None = None,     # ?history_id=3  (filter by scan run)
):
    filters = LeadFilterParams(
        status=status,
        category=category,
        platform=platform,
        min_score=min_score,
        history_id=history_id,
    )
    return await lead_service.get_leads(db, current_user, campaign_id, filters)


@router.get("/campaigns/{campaign_id}/leads/{lead_id}")
async def get_lead(
    campaign_id: int,
    lead_id: str,   # UUID
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await lead_service.get_lead(db, current_user, campaign_id, lead_id)


@router.patch("/campaigns/{campaign_id}/leads/{lead_id}/status")
async def update_lead_status(
    campaign_id: int,
    lead_id: str,
    status: str,    # ?status=replied
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await lead_service.update_status(db, current_user, campaign_id, lead_id, status)


@router.get("/campaigns/{campaign_id}/leads/{lead_id}/similar")
async def get_similar_leads(
    campaign_id: int,
    lead_id: str,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
    limit: int = 10,
    threshold: float = 0.5,
):
    """Returns leads with similar embeddings to the given lead."""
    return await lead_service.get_similar(db, current_user, campaign_id, lead_id, limit, threshold)


# ── Lead Actions ───────────────────────────────────────────────────────────────

@router.get("/campaigns/{campaign_id}/leads/{lead_id}/actions")
async def get_lead_actions(
    campaign_id: int,
    lead_id: str,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await action_service.get_actions(db, current_user, lead_id)


@router.post("/campaigns/{campaign_id}/leads/{lead_id}/actions", status_code=status.HTTP_201_CREATED)
async def create_lead_action(
    campaign_id: int,
    lead_id: str,
    body: CreateLeadActionBody,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await action_service.create_action(db, current_user, lead_id, body)


@router.delete("/campaigns/{campaign_id}/leads/{lead_id}/actions/{action_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_action(
    campaign_id: int,
    lead_id: str,
    action_id: str,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await action_service.delete_action(db, current_user, action_id)