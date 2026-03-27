"""
src/infra/runpod/playstore/services/review_fetch.py
────────────────────────────────────────────────────
Fetches reviews for a single app_id using google-play-scraper.
Returns a list of normalised dicts ready to be persisted as PlaystoreReview rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google_play_scraper import Sort, reviews, app as gplay_app


MAX_REVIEWS = 500   # default cap; override via max_reviews arg


def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def fetch_app_info(app_id: str) -> dict[str, Any]:
    """Return basic metadata (name, icon, score) for an app."""
    try:
        info = gplay_app(app_id, lang="en", country="us")
        return {
            "app_id":  app_id,
            "title":   info.get("title", ""),
            "score":   info.get("score"),
            "installs": info.get("installs"),
        }
    except Exception as e:
        return {"app_id": app_id, "title": "", "error": str(e)}


def fetch_reviews_for_app(
    app_id: str,
    max_reviews: int = MAX_REVIEWS,
    lang: str = "en",
    country: str = "us",
) -> list[dict[str, Any]]:
    """
    Fetch up to `max_reviews` reviews for `app_id`.
    Returns a list of normalised dicts.
    """
    result_list = []
    continuation_token = None

    while len(result_list) < max_reviews:
        batch_size = min(200, max_reviews - len(result_list))
        try:
            batch, continuation_token = reviews(
                app_id,
                lang=lang,
                country=country,
                sort=Sort.NEWEST,
                count=batch_size,
                continuation_token=continuation_token,
            )
        except Exception:
            break

        if not batch:
            break

        for r in batch:
            result_list.append({
                "review_id":      r.get("reviewId"),
                "username":       r.get("userName"),
                "content":        r.get("content"),
                "score":          r.get("score"),
                "thumbs_up":      r.get("thumbsUpCount"),
                "review_created": _parse_dt(r.get("at")),
                "reply_content":  r.get("replyContent"),
                "reply_date":     _parse_dt(r.get("repliedAt")),
            })

        if not continuation_token or len(batch) < batch_size:
            break

    return result_list