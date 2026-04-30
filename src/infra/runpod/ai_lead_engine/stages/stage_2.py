import uuid
import random
import asyncio
import aiohttp
import numpy as np
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sentence_transformers import SentenceTransformer

from src.core.database import AsyncSessionLocal
from src.app.ai_lead_engine.model import Lead, LeadPost
from src.infra.runpod.ai_lead_engine.stages.stage_1 import PrepareResult
from src.infra.runpod.ai_lead_engine.services.embeding import encode_lead_text


BASE_URL    = "https://www.reddit.com/search.json"
HEADERS     = {"User-Agent": "tactbyte-south-AlmaLinux ai-lead-engine/1.2"}

CONCURRENCY = 5    # max parallel Reddit requests
RATE_SLEEP  = 1.0  # base sleep per slot (seconds)
JITTER_MAX  = 0.5  # max extra random delay


# ─── Output contract ──────────────────────────────────────────────────────────

@dataclass
class FetchResult:
    campaign_id:          int
    campaign_history_id:  int
    lead_ids:             list[uuid.UUID]


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _fetch_reddit(
    session:   aiohttp.ClientSession,
    query:     str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, list]:
    async with semaphore:
        try:
            url = f"{BASE_URL}?q={query}&sort=new&t=week&limit=50&type=posts"
            async with session.get(url, headers=HEADERS) as resp:
                if resp.status != 200:
                    print(f"[stage_2] Reddit {resp.status} for query={query!r}")
                    return query, []
                data = await resp.json()
                return query, data["data"]["children"]
        except Exception as e:
            print(f"[stage_2] Fetch error for query={query!r} — {e}")
            return query, []
        finally:
            await asyncio.sleep(RATE_SLEEP + random.uniform(0.0, JITTER_MAX))


# ─── Stage 2 ──────────────────────────────────────────────────────────────────

async def stage_2_fetch(prepare: PrepareResult) -> FetchResult:
    """
    1. Fetch Reddit posts for each keyword (semaphore + jitter)
    2. Deduplicate by post_id
    3. Embed each post using shared encode_lead_text
    4. Bulk insert Lead + LeadPost rows (status=new, scores=None)
    """
    campaign        = prepare.campaign
    history         = prepare.history
    keyword_strings = prepare.keyword_strings

    # ── 1. Fetch Reddit with rate limiting ────────────────────────────────────
    print(f"[stage_2] Fetching Reddit for {len(keyword_strings)} keywords")

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession() as session:
        tasks        = [_fetch_reddit(session, q, semaphore) for q in keyword_strings]
        results_list = await asyncio.gather(*tasks)

    # ── 2. Deduplicate ────────────────────────────────────────────────────────
    seen, lead_meta = set(), []

    for query, results in results_list:
        if not results:
            continue
        for item in results:
            p       = item.get("data")
            post_id = p.get("id") if p else None
            if not post_id or post_id in seen:
                continue
            seen.add(post_id)
            lead_meta.append((uuid.uuid4(), query, p))

    if not lead_meta:
        print(f"[stage_2] No posts found for campaign_id={campaign.id}")
        return FetchResult(
            campaign_id=campaign.id,
            campaign_history_id=history.id,
            lead_ids=[],
        )

    print(f"[stage_2] {len(lead_meta)} unique posts collected, embedding...")

    # ── 3. Embed using shared encoder ─────────────────────────────────────────
    lead_rows_temp = []
    for (lead_uuid, query, p) in lead_meta:
        vector, text = encode_lead_text(p.get("title"), p.get("selftext"))
        if vector is None:
            continue
        lead_rows_temp.append((lead_uuid, query, p, vector, text))

    if not lead_rows_temp:
        print(f"[stage_2] No embeddable posts for campaign_id={campaign.id}")
        return FetchResult(
            campaign_id=campaign.id,
            campaign_history_id=history.id,
            lead_ids=[],
        )

    print(f"[stage_2] {len(lead_rows_temp)} posts embedded")

    # ── 4. Build rows ─────────────────────────────────────────────────────────
    now       = datetime.now(timezone.utc)
    lead_rows = []
    post_rows = []
    lead_ids  = []

    for lead_uuid, query, p, vector, text in lead_rows_temp:   # ← fixed: iterate temp
        likes    = p.get("ups") or 0
        comments = p.get("num_comments") or 0

        lead_rows.append({
            "id":                   lead_uuid,
            "campaign_id":          campaign.id,
            "campaign_history_id":  history.id,
            "platform":             "reddit",
            "status":               "new",
            "search_keyword":       query,
            "embedding":            vector,        # ← already a list, no .tolist()
            "embedding_text":       text,
            "embedded_at":          now,
            "ai_score":             None,
            "similarity_score":     None,
            "intent":               None,
        })

        post_rows.append({
            "id":               uuid.uuid4(),
            "lead_id":          lead_uuid,
            "external_id":      p.get("id"),
            "title":            p.get("title"),
            "content":          p.get("selftext"),
            "author":           p.get("author"),
            "url":              "https://reddit.com" + p.get("permalink", ""),
            "likes":            likes,
            "comments_count":   comments,
            "post_created_at":  datetime.fromtimestamp(p["created_utc"], tz=timezone.utc)
                                if p.get("created_utc") else None,
            "subreddit":        p.get("subreddit"),
            "subreddit_id":     p.get("subreddit_id"),
            "fetch_ok":         True,
            "fetched_at":       now,
        })

        lead_ids.append(lead_uuid)

    # ── 5. Bulk insert ────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        await db.execute(
            insert(Lead)
            .values(lead_rows)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db.execute(
            insert(LeadPost)
            .values(post_rows)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db.commit()

    print(f"[stage_2] Saved {len(lead_rows)} leads for campaign_id={campaign.id}")

    return FetchResult(
        campaign_id=campaign.id,
        campaign_history_id=history.id,
        lead_ids=lead_ids,
    )