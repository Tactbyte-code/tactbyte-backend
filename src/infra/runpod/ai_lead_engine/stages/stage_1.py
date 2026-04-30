from dataclasses import dataclass

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.app.ai_lead_engine.model import Campaign, CampaignHistory, Keyword
from src.infra.runpod.ai_lead_engine.services.embeding import apply_campaign_embedding


# ─── Output contract ──────────────────────────────────────────────────────────

@dataclass
class PrepareResult:
    campaign:         Campaign
    history:          CampaignHistory
    keyword_strings:  list[str]


# ─── Stage 1 ──────────────────────────────────────────────────────────────────

async def stage_1_prepare(campaign_history_id: int) -> PrepareResult:
    """
    1. Load CampaignHistory + Campaign
    2. Generate embeddings if missing
    3. Load positive keywords — fail if none
    """
    async with AsyncSessionLocal() as db:

        # ── 1. Load history ────────────────────────────────────────────────────
        history = await db.get(CampaignHistory, campaign_history_id)
        if not history:
            raise ValueError(f"CampaignHistory {campaign_history_id} not found")

        # ── 2. Load campaign ───────────────────────────────────────────────────
        campaign = await db.get(Campaign, history.campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {history.campaign_id} not found")

        # ── 3. Ensure embeddings exist ─────────────────────────────────────────
        if campaign.service_embedding is None or campaign.buyer_embedding is None:
            print(f"[stage_1] Generating embeddings for campaign_id={campaign.id}")
            apply_campaign_embedding(campaign)
            await db.commit()
            await db.refresh(campaign)
            print(f"[stage_1] Embeddings saved for campaign_id={campaign.id}")
        else:
            print(f"[stage_1] Embeddings already exist for campaign_id={campaign.id}")

        # ── 4. Load keywords ───────────────────────────────────────────────────
        result = await db.execute(
            select(Keyword)
            .where(Keyword.campaign_id == campaign.id)
            .where(Keyword.keyword.isnot(None))
            .where(Keyword.match_type == "positive")
        )
        keyword_strings = [k.keyword for k in result.scalars().all()]

        if not keyword_strings:
            raise ValueError(f"No positive keywords found for campaign_id={campaign.id}")

        print(f"[stage_1] Found {len(keyword_strings)} keywords for campaign_id={campaign.id}")

    return PrepareResult(
        campaign=campaign,
        history=history,
        keyword_strings=keyword_strings,
    )