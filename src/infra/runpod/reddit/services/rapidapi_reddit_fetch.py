#!/usr/bin/env python3
"""
Reddit .json API fetch — parallel, rate-limited, with retry.

For each VertexResult URL, fetches the Reddit thread as a point-in-time
snapshot: post metadata + full comment tree (author, body, score, depth).

NOTE: No date filtering here — all posts are fetched and stored.
      Date filtering happens in the handler AFTER fetch so we have a
      complete audit trail. Only date-valid posts are passed to Gate 2.

Rate limit strategy:
  - Reddit public API: ~60 req/min without auth
  - Concurrency:       5 simultaneous requests
  - Batch delay:       2.0s between batches  → ~30 req/min safe ceiling
  - Per-request delay: 0.3s jitter           → avoids burst fingerprint
  - Retry:             3 attempts with exponential backoff (1s, 2s, 4s)
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from src.core.settings import settings

import aiohttp

import runpod
log = runpod.RunPodLogger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONCURRENCY    = 2
BATCH_DELAY_S  = 2.0
JITTER_S       = 0.3
MAX_RETRIES    = 3
BACKOFF_BASE_S = 1.0

_RAPIAPI_URL= "https://reddit34.p.rapidapi.com/v1/reddit/post"

HEADERS = {
    "x-rapidapi-key": settings.RAPIDAPI_KEY,
    "x-rapidapi-host": "reddit34.p.rapidapi.com",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# Comment tree parser
# ---------------------------------------------------------------------------
def _parse_comment(comment: dict, depth: int = 0 , reddit_url: str = '') -> list[dict[str, Any]]:
    """
    Recursively builds a nested Reddit comment tree.
    Each dict contains its direct children under 'replies'.
    Skips "more" continuation objects and deleted/removed comments.
    """
    body = comment.get("content", "")
    if body in ("[deleted]", "[removed]", ""):
        return []
    
    node = {
        "id": comment.get("id", ""),
        "author": comment.get("author", ""),
        "body": body,
        "score": comment.get("score", 0),
        "depth": depth,
        "url": f"{reddit_url}/comment/{comment.get('id', '')}",
        "created_utc": (
            datetime.fromtimestamp(
                comment["created_utc"],
                tz=timezone.utc,
            ).isoformat()
            if comment.get("created_utc")
            else None
        ),
        "replies": [],
    }

    for reply in comment.get("replies", []):
        parsed = _parse_comment(reply, depth + 1, reddit_url)
        if parsed:
            node["replies"].extend(parsed)

    return [node]

# ---------------------------------------------------------------------------
# Single URL fetch
# ---------------------------------------------------------------------------

async def _fetch_one(
    session: aiohttp.ClientSession,
    vertex_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Fetches a single Reddit thread via the public .json API.
    Retries up to MAX_RETRIES times with exponential backoff.

    Always returns the vertex_result dict enriched with reddit_* fields.
    reddit_fetch_ok=False means fetch failed (deleted/banned/error).
    Date filtering is NOT done here — caller handles it.
    """

    params = { "url": vertex_result["url"],}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await asyncio.sleep(JITTER_S * attempt)

            # call rapid api reddit post detail end point
            async with session.get(
                _RAPIAPI_URL,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=10),
                params=params
            ) as resp:

                # Hard failure — no point retrying
                if resp.status == 404:
                    log.warn(f"[Reddit] 404 — skipping {vertex_result['url']}")
                    return {**vertex_result, "reddit_fetch_ok": False}

                # Transient errors — retry
                if resp.status in (403, 429, 500, 503):
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history, status=resp.status
                    )

                if resp.status != 200:
                    log.warn(f"[Reddit] Unexpected {resp.status} for {vertex_result['url']}")
                    return {**vertex_result, "reddit_fetch_ok": False}

                payload = await resp.json(content_type=None)

                if not isinstance(payload, dict):
                    return {**vertex_result, "reddit_fetch_ok": False}

                body = payload.get("body")

                if not isinstance(body, dict):
                    return {**vertex_result, "reddit_fetch_ok": False}

                post_data = body.get("post")

                if not isinstance(post_data, dict):
                    return {**vertex_result, "reddit_fetch_ok": False}

                comment_nodes = body.get("post_comments", [])

                created_utc = post_data.get("created_utc")
                post_dt     = datetime.fromtimestamp(created_utc, tz=timezone.utc) if created_utc else None

                reddit_url = f"https://reddit.com{post_data.get('permalink', '')}"
                comments = []
                for node in comment_nodes:
                    comments.extend(_parse_comment(node, depth=0, reddit_url=reddit_url,))

                return {
                    **vertex_result,
                    "reddit_id":           post_data.get("id", ""),
                    "reddit_fetch_ok":     True,
                    "reddit_fetched_at":   datetime.now(tz=timezone.utc).isoformat(),
                    "reddit_title":        post_data.get("title", ""),
                    "reddit_selftext":     post_data.get("selftext", ""),
                    "reddit_author":       post_data.get("author", ""),
                    "reddit_subreddit_id": post_data.get("subreddit_id", ""),
                    "reddit_subreddit":    post_data.get("subreddit", ""),
                    "reddit_score":        post_data.get("score", 0),
                    "reddit_num_comments": post_data.get("num_comments", 0),
                    "reddit_created_utc":  post_dt.isoformat() if post_dt else None,
                    "reddit_url":          reddit_url,      
                    "reddit_comments":     comments,
                }

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            wait = BACKOFF_BASE_S * (2 ** (attempt - 1))
            if attempt < MAX_RETRIES:
                log.warn(
                    f"[Reddit] Attempt {attempt}/{MAX_RETRIES} failed for "
                    f"{vertex_result['url']} — retrying in {wait}s: {e}"
                )
                await asyncio.sleep(wait)
            else:
                log.error(f"[Reddit] All {MAX_RETRIES} attempts failed for {vertex_result['url']}: {e}")
                return {**vertex_result, "reddit_fetch_ok": False}

    return {**vertex_result, "reddit_fetch_ok": False}


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

async def _fetch_batch(
    session: aiohttp.ClientSession,
    batch: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tasks = [_fetch_one(session, item) for item in batch]
    return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def fetch_reddit_posts(
    vertex_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Fetches Reddit post + full comment tree for each URL in vertex_results.

    Runs in parallel batches of CONCURRENCY=5 with smart timing to stay
    safely under Reddit's ~60 req/min rate limit.

    NOTE: All posts are fetched regardless of date. Date filtering is the
          caller's responsibility — only pass date-valid posts to Gate 2.

    Args:
        vertex_results: List of result dicts from run_vertex_search().

    Returns:
        Same list enriched with reddit_* fields on each dict.
        reddit_fetch_ok=True  → post fetched successfully
        reddit_fetch_ok=False → deleted, banned, or fetch failed
    """
    if not vertex_results:
        return []

    batches = [
        vertex_results[i : i + CONCURRENCY]
        for i in range(0, len(vertex_results), CONCURRENCY)
    ]

    log.info(
        f"[Reddit] Fetching {len(vertex_results)} URLs "
        f"in {len(batches)} batches of {CONCURRENCY}"
    )

    results: list[dict[str, Any]] = []

    async with aiohttp.ClientSession() as session:
        for i, batch in enumerate(batches):
            batch_start   = time.monotonic()
            batch_results = await _fetch_batch(session, batch)
            results.extend(batch_results)

            ok    = sum(1 for r in batch_results if r.get("reddit_fetch_ok"))
            total = len(batch_results)
            log.info(f"[Reddit] Batch {i+1}/{len(batches)} — {ok}/{total} fetched ok")

            # Smart timing — sleep only the remaining delta to fill BATCH_DELAY_S
            if i < len(batches) - 1:
                elapsed = time.monotonic() - batch_start
                sleep   = max(0.0, BATCH_DELAY_S - elapsed)
                if sleep:
                    await asyncio.sleep(sleep)

    ok_count   = sum(1 for r in results if r.get("reddit_fetch_ok"))
    skip_count = len(results) - ok_count
    log.info(f"[Reddit] Complete — {ok_count} fetched, {skip_count} failed/skipped")
    return results
