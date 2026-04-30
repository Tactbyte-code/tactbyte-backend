import uuid
import numpy as np
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from src.core.database import AsyncSessionLocal
from src.app.ai_lead_engine.model import Campaign, Lead, LeadPost
from src.infra.runpod.ai_lead_engine.stages.stage_2 import FetchResult


# ─── Config ───────────────────────────────────────────────────────────────────

SERVICE_SCORE_MIN = 0.25   # just enough to be topic-relevant
BUYER_SCORE_MIN   = 0.35   # must show buying intent
BUYER_SCORE_WARM  = 0.35
BUYER_SCORE_HOT   = 0.5


# ─── Output contract ──────────────────────────────────────────────────────────

@dataclass
class VectorFilterResult:
    campaign_id:          int
    campaign_history_id:  int
    surviving_lead_ids:   list[uuid.UUID]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _cosine_similarity(a, b) -> float:
    if a is None or b is None:
        return 0.0
    a, b = np.array(a), np.array(b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(np.dot(a, b) / norm)


def _normalize_score(x: float) -> int:
    return int(round(max(0, min(x, 1)) * 10))


def _buyer_type(buyer_score: float) -> str:
    if buyer_score >= BUYER_SCORE_HOT:
        return "hot"
    if buyer_score >= BUYER_SCORE_WARM:
        return "warm"
    return "cold"


# ─── Stage 3 ──────────────────────────────────────────────────────────────────

async def stage_3_vector_filter(fetch: FetchResult) -> VectorFilterResult:
    """
    1. Load all new leads by lead_ids — eager load post to avoid lazy load error
    2. Score each against campaign service + buyer embeddings
    3. Bulk update:
       - status=ignored  → service_score < 0.5 or buyer_score < 0.5
       - status=replied  → passed vector filter, ready for AI stage
         (repurposing as intermediate; add a real 'filtered' status if preferred)
    4. Return surviving lead_ids for stage 4
    """
    if not fetch.lead_ids:
        print(f"[stage_3] No leads to filter for campaign_id={fetch.campaign_id}")
        return VectorFilterResult(
            campaign_id=fetch.campaign_id,
            campaign_history_id=fetch.campaign_history_id,
            surviving_lead_ids=[],
        )

    async with AsyncSessionLocal() as db:

        # ── 1. Load campaign embeddings ───────────────────────────────────────
        campaign = await db.get(Campaign, fetch.campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {fetch.campaign_id} not found")

        service_emb = np.array(campaign.service_embedding)
        buyer_emb   = np.array(campaign.buyer_embedding)

        # ── 2. Load leads + eagerly load post to avoid MissingGreenlet ────────
        result = await db.execute(
            select(Lead)
            .where(Lead.id.in_(fetch.lead_ids))
            .where(Lead.status == "new")
            .options(selectinload(Lead.post))   # load LeadPost in same query
        )
        leads = result.scalars().all()

        print(f"[stage_3] Scoring {len(leads)} leads for campaign_id={fetch.campaign_id}")

        # ── 3. Score each lead ────────────────────────────────────────────────
        now         = datetime.now(timezone.utc)
        update_rows = []
        surviving_ids: list[uuid.UUID] = []
        ignored_ids:   list[uuid.UUID] = []

        for lead in leads:
            vector        = np.array(lead.embedding)
            service_score = _cosine_similarity(vector, service_emb)
            buyer_score   = _cosine_similarity(vector, buyer_emb)

            if service_score < SERVICE_SCORE_MIN or buyer_score < BUYER_SCORE_MIN:
                ignored_ids.append(lead.id)
                update_rows.append({
                    "id":               lead.id,
                    "status":           "ignored",
                    "similarity_score": round(service_score, 4),
                    "intent":           f"buyer:{_buyer_type(buyer_score)}",
                })
                continue

            # engagement boost from eagerly loaded post
            post     = lead.post
            likes    = post.likes           if post else 0
            comments = post.comments_count  if post else 0
            eng_score = min((likes + comments * 2) / 100, 1)

            final_score = ((service_score * 0.6) + (buyer_score * 0.4)) * 0.8 + eng_score * 0.2

            surviving_ids.append(lead.id)
            update_rows.append({
                "id":               lead.id,
                "status":           "new",            # keep as new — stage 4 will confirm/ignore
                "similarity_score": round(service_score, 4),
                "intent":           f"buyer:{_buyer_type(buyer_score)}",
                "vector_score":     round(final_score, 4),
            })

        # ── 4. Bulk update ────────────────────────────────────────────────────
        if update_rows:
            await db.execute(update(Lead), update_rows)
            await db.commit()

        print(
            f"[stage_3] campaign_id={fetch.campaign_id} "
            f"survived={len(surviving_ids)} ignored={len(ignored_ids)}"
        )

    return VectorFilterResult(
        campaign_id=fetch.campaign_id,
        campaign_history_id=fetch.campaign_history_id,
        surviving_lead_ids=surviving_ids,
    )