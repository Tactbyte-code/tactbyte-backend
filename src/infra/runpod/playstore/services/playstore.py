"""
src/infra/runpod/playstore/services/playstore.py
─────────────────────────────────────────────────
RunPod pipeline handlers for the Play Store module.
  _handle_playstore_search  → fetch reviews → persist → mark FETCH_COMPLETE
  _handle_playstore_summary → load reviews → summarise → persist → mark COMPLETED
"""
from __future__ import annotations

import runpod
from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.core.settings import settings
from src.infra.runpod.llm import get_client
from src.app.playstore.model import (
    PlaystoreQuery,
    PlaystoreQueryStatus,
    PlaystoreFailureReason,
    PlaystoreReview,
    PlaystoreSummary,
)
from src.infra.runpod.playstore.services.review_fetch import fetch_app_info, fetch_reviews_for_app
from src.infra.runpod.playstore.services.summarizer import run_summarizer

log = runpod.RunPodLogger()


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _fail_record(query_id: str, reason: str = PlaystoreFailureReason.UNKNOWN) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlaystoreQuery).where(PlaystoreQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if record:
            record.fail_step(reason)
            await db.commit()
    return {"statusCode": 500, "body": {"error": reason}}


# ─── Search (fetch reviews) ───────────────────────────────────────────────────

async def _handle_playstore_search(query_id: str) -> dict:
    log.info(f"[PLAYSTORE][FETCH] Starting | query_id={query_id}")

    # 1. Load record
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlaystoreQuery).where(PlaystoreQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            log.error(f"[PLAYSTORE][FETCH] Query not found | query_id={query_id}")
            return {"statusCode": 404, "body": {"error": "Query not found"}}
        app_id = record.app_id
        log.info(f"[PLAYSTORE][FETCH] Loaded record | app_id={app_id}")

    # 2. Fetch app metadata
    log.info(f"[PLAYSTORE][FETCH] Fetching app info for {app_id}")
    app_info = fetch_app_info(app_id)
    app_name = app_info.get("title") or app_id
    log.info(f"[PLAYSTORE][FETCH] App name: {app_name}")

    # 3. Fetch reviews
    log.info(f"[PLAYSTORE][FETCH] Scraping reviews for {app_id}")
    try:
        raw_reviews = fetch_reviews_for_app(app_id, max_reviews=500)
    except Exception as e:
        log.error(f"[PLAYSTORE][FETCH] Review fetch failed: {e}")
        return await _fail_record(query_id, PlaystoreFailureReason.FETCH_ERROR)

    if not raw_reviews:
        log.warn(f"[PLAYSTORE][FETCH] No reviews returned for {app_id}")
        return await _fail_record(query_id, PlaystoreFailureReason.NO_RESULTS)

    log.info(f"[PLAYSTORE][FETCH] Fetched {len(raw_reviews)} reviews")

    # 4. Persist reviews
    try:
        async with AsyncSessionLocal() as db:
            for r in raw_reviews:
                row = PlaystoreReview(
                    query_id=       query_id,
                    app_id=         app_id,
                    review_id=      r.get("review_id"),
                    username=       r.get("username"),
                    content=        r.get("content"),
                    score=          r.get("score"),
                    thumbs_up=      r.get("thumbs_up"),
                    review_created= r.get("review_created"),
                    reply_content=  r.get("reply_content"),
                    reply_date=     r.get("reply_date"),
                )
                db.add(row)
            await db.commit()
        log.info(f"[PLAYSTORE][FETCH] Persisted {len(raw_reviews)} reviews")
    except Exception as e:
        log.error(f"[PLAYSTORE][FETCH] Failed to persist reviews: {e}")
        return await _fail_record(query_id, PlaystoreFailureReason.UNKNOWN)

    # 5. Mark FETCH_COMPLETE and save app_name
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlaystoreQuery).where(PlaystoreQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if record:
            record.app_name = app_name
            record.complete_step(PlaystoreQueryStatus.FETCH_COMPLETE)
            await db.commit()
            log.info(f"[PLAYSTORE][FETCH] Marked FETCH_COMPLETE | query_id={query_id}")

    return {"statusCode": 200}


# ─── Summary ──────────────────────────────────────────────────────────────────

async def _handle_playstore_summary(query_id: str) -> dict:
    log.info(f"[PLAYSTORE][SUMMARY] Starting | query_id={query_id}")
 
    # 1. Load record — guard against missing / already-completed / duplicate summary
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlaystoreQuery).where(PlaystoreQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return {"statusCode": 404, "body": {"error": "Query not found"}}
 
        if record.status == PlaystoreQueryStatus.COMPLETED:
            return {"statusCode": 409, "body": {"error": "Summary already completed"}}
 
        app_id   = record.app_id
        app_name = record.app_name or app_id
 
        existing = await db.execute(
            select(PlaystoreSummary).where(PlaystoreSummary.query_id == query_id)
        )
        if existing.scalar_one_or_none():
            return {"statusCode": 409, "body": {"error": "Summary already exists"}}
 
    # 2. Load reviews
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PlaystoreReview).where(PlaystoreReview.query_id == query_id)
            )
            all_rows = result.scalars().all()
    except Exception as e:
        log.error(f"[PLAYSTORE][SUMMARY] Failed to load reviews: {e}")
        return await _fail_record(query_id, PlaystoreFailureReason.UNKNOWN)
 
    log.info(f"[PLAYSTORE][SUMMARY] {len(all_rows)} reviews loaded")
 
    approved_reviews = [
        {
            "review_id":      r.review_id,
            "username":       r.username,
            "content":        r.content,
            "score":          r.score,
            "thumbs_up":      r.thumbs_up,
            "review_created": str(r.review_created) if r.review_created else None,
            "reply_content":  r.reply_content,
        }
        for r in all_rows
    ]
 
    # 3. Build LLM client
    client = get_client(
        provider=   settings.LLM_PROVIDER,
        model=      settings.LLM_MODEL,
        api_key=    settings.LLM_API_KEY,
        base_url=   settings.LLM_API_BASE_URL,
        max_tokens= settings.LLM_MAX_TOKENS,
    )
 
    # 4. Run summarizer
    try:
        final_output = run_summarizer(
            reviews=  approved_reviews,
            app_name= app_name,
            client=   client,
        )
    except Exception as e:
        log.error(f"[PLAYSTORE][SUMMARY] Summarization failed: {e}")
        return await _fail_record(query_id, PlaystoreFailureReason.SUMMARIZATION_ERROR)
 
    if not final_output:
        log.error(f"[PLAYSTORE][SUMMARY] Empty output | query_id={query_id}")
        return await _fail_record(query_id, PlaystoreFailureReason.SUMMARIZATION_ERROR)
 
    # 5. Persist summary + mark COMPLETED in a single atomic transaction
    try:
        async with AsyncSessionLocal() as db:
            db.add(PlaystoreSummary(
                query_id=             query_id,
                app_id=               app_id,
                app_name=             app_name,
                analyzed_at=          final_output.get("analyzed_at"),
                direct_answer=        final_output.get("direct_answer"),
                executive_summary=    final_output.get("executive_summary"),
                overall_sentiment=    final_output.get("overall_sentiment"),
                total_signals=        final_output.get("total_signals"),
                average_rating=       final_output.get("average_rating"),
                themes=               final_output.get("themes"),
                market_signals=       final_output.get("market_signals"),
                actionable_next_steps=final_output.get("actionable_next_steps"),
                rating_breakdown=     final_output.get("rating_breakdown"),
                meta=                 final_output.get("meta"),
            ))
 
            result = await db.execute(
                select(PlaystoreQuery).where(PlaystoreQuery.id == query_id)
            )
            record = result.scalar_one_or_none()
            if record:
                record.complete_step(PlaystoreQueryStatus.COMPLETED)
 
            await db.commit()
            log.info(
                f"[PLAYSTORE][SUMMARY] Saved + marked COMPLETED | query_id={query_id} "
                f"themes={len(final_output.get('themes', []))} "
                f"steps={len(final_output.get('actionable_next_steps', []))}"
            )
 
    except Exception as e:
        log.error(f"[PLAYSTORE][SUMMARY] Atomic save failed — rolling back: {e}")
        return await _fail_record(query_id, str(e))
 
    return {"statusCode": 200}