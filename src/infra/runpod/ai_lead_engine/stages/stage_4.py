import random
import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from src.core.database import AsyncSessionLocal
from src.app.ai_lead_engine.model import Campaign, Lead, LeadPost
from src.infra.runpod.ai_lead_engine.stages.stage_3 import VectorFilterResult
from src.infra.runpod.ai_lead_engine.services.lead_filter import get_lead_agent


# ─── Config ───────────────────────────────────────────────────────────────────

LEAD_SCORE_THRESHOLD = 7     # 0–10, >= this → confirmed (status=replied)
CONCURRENCY          = 10    # max parallel LLM calls
RATE_SLEEP           = 1.0   # base sleep per slot
JITTER_MAX           = 0.5   # max extra jitter


# ─── Output contract ──────────────────────────────────────────────────────────

@dataclass
class AIFilterResult:
    campaign_id:          int
    campaign_history_id:  int
    confirmed_count:      int
    rejected_count:       int


# ─── Stage 4 ──────────────────────────────────────────────────────────────────

async def stage_4_ai_filter(vector: VectorFilterResult) -> AIFilterResult:
    """
    1. Load surviving leads + posts (eager) from DB
    2. Score each via LLM (0–10) with semaphore + jitter for 60 req/min
    3. Update:
       - status=replied  → score >= threshold  (confirmed lead)
       - status=ignored  → score <  threshold  (rejected)
       - intent          → LLM reasoning stored here (no ai_reasoning column)
       - ai_score        → final LLM score
    4. Return summary counts
    """
    if not vector.surviving_lead_ids:
        print(f"[stage_4] No leads to score for campaign_id={vector.campaign_id}")
        return AIFilterResult(
            campaign_id=vector.campaign_id,
            campaign_history_id=vector.campaign_history_id,
            confirmed_count=0,
            rejected_count=0,
        )

    async with AsyncSessionLocal() as db:

        # ── 1. Load campaign (scalar fields safe after session closes) ─────────
        campaign = await db.get(Campaign, vector.campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {vector.campaign_id} not found")

        # snapshot scalars before session closes
        description = campaign.description
        intent      = campaign.intent

        # ── 2. Load surviving leads + eagerly load post ────────────────────────
        result = await db.execute(
            select(Lead)
            .where(Lead.id.in_(vector.surviving_lead_ids))
            .where(Lead.status == "new")
            .options(selectinload(Lead.post))
        )
        leads = result.scalars().all()

    print(f"[stage_4] Scoring {len(leads)} leads via LLM for campaign_id={vector.campaign_id}")

    # ── 3. Score via LLM with semaphore + jitter ───────────────────────────────
    agent     = get_lead_agent()
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def score_one(lead: Lead) -> dict | None:
        post = lead.post
        if not post or not post.title:
            return None
        async with semaphore:
            try:
                result = await agent.ainvoke({
                    "messages": (
                        f"Service Description: {description}\n"
                        f"Target Intent: {intent}\n"
                        f"Reddit Title: {post.title}\n\n"
                        f"Score this title as a potential lead."
                    )
                })
                scored = result["structured_response"]
                return {
                    "lead_id":   lead.id,
                    "score":     scored.score,
                    "is_lead":   scored.is_lead,
                    "reasoning": scored.reasoning,
                }
            except Exception as e:
                print(f"[stage_4] Failed lead_id={lead.id} — {e}")
                return None
            finally:
                await asyncio.sleep(RATE_SLEEP + random.uniform(0.0, JITTER_MAX))

    scored_rows = await asyncio.gather(*[score_one(lead) for lead in leads])

    # ── 4. Classify + build update rows ───────────────────────────────────────
    now           = datetime.now(timezone.utc)
    update_rows   = []
    confirmed_ids: list[uuid.UUID] = []
    rejected_ids:  list[uuid.UUID] = []

    for scored in scored_rows:
        if scored is None:
            continue

        is_confirmed = scored["score"] >= LEAD_SCORE_THRESHOLD

        if is_confirmed:
            confirmed_ids.append(scored["lead_id"])
        else:
            rejected_ids.append(scored["lead_id"])

        update_rows.append({
            "id":       scored["lead_id"],
            "status":   "replied"  if is_confirmed else "ignored",
            "ai_score": scored["score"],
            "intent":   scored["reasoning"],   # no ai_reasoning col → store in intent
        })

    # ── 5. Bulk update ─────────────────────────────────────────────────────────
    if update_rows:
        async with AsyncSessionLocal() as db:
            await db.execute(update(Lead), update_rows)
            await db.commit()

    print(
        f"[stage_4] campaign_id={vector.campaign_id} "
        f"confirmed={len(confirmed_ids)} rejected={len(rejected_ids)}"
    )

    return AIFilterResult(
        campaign_id=vector.campaign_id,
        campaign_history_id=vector.campaign_history_id,
        confirmed_count=len(confirmed_ids),
        rejected_count=len(rejected_ids),
    )