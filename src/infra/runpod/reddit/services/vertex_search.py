#!/usr/bin/env python3
"""
GATE 1 — Vertex AI Search (parallel, scoped to Reddit)

For each query in rich_context["queries"], fires a Vertex AI
Discoveryengine search request concurrently and returns a flat,
deduplicated list of raw result dicts ready for the Reddit .json API stage.
"""

import asyncio
import hashlib
import json
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import discoveryengine_v1 as discoveryengine
from google.oauth2 import service_account

from src.core.settings import settings

import runpod
log = runpod.RunPodLogger()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_client() -> discoveryengine.SearchServiceAsyncClient:
    """
    Builds the async Vertex AI Search client using
    settings.GOOGLE_APPLICATION_CREDENTIALS_JSON (JSON string from .env).
    """
    creds_info  = json.loads(settings.GOOGLE_APPLICATION_CREDENTIALS_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return discoveryengine.SearchServiceAsyncClient(credentials=credentials)


def _serving_config() -> str:
    return (
        f"projects/{settings.DISCOVERY_PROJECT_ID}"
        f"/locations/{settings.DISCOVERY_LOCATION}"
        f"/collections/{settings.DISCOVERY_COLLECTION}"
        f"/engines/{settings.DISCOVERY_ENGINE_ID}"
        f"/servingConfigs/{settings.DISCOVERY_SERVING_CONFIG}"
    )


def _parse_results(
    response: discoveryengine.SearchResponse,
    query: str,
) -> list[dict[str, Any]]:
    results = []
    for result in response.results:
        doc      = result.document
        derived  = dict(doc.derived_struct_data)
        struct   = dict(doc.struct_data) if doc.struct_data else {}

        title    = derived.get("title") or struct.get("title", "")
        link     = derived.get("link")  or struct.get("link",  "")
        snippets = derived.get("snippets", [{}])

        snippet_text = ""
        if isinstance(snippets, list) and snippets:
            snippet_text = snippets[0].get("snippet", "")

        if not link:
            continue

        results.append({
            "query":   query,
            "title":   title,
            "url":     link,
            "snippet": snippet_text,
            "doc_id":  doc.id,
        })
    return results


# ---------------------------------------------------------------------------
# Single-query search
# ---------------------------------------------------------------------------

async def _search_one(
    client: discoveryengine.SearchServiceAsyncClient,
    serving_cfg: str,
    query: str,
    page_size: int,
) -> list[dict[str, Any]]:
    try:
        request = discoveryengine.SearchRequest(
            serving_config=serving_cfg,
            query=query,
            page_size=page_size,
        )
        response = await client.search(request)
        results  = _parse_results(response, query)
        log.info(f"[GATE 1] query='{query}' → {len(results)} results")
        return results
    except GoogleAPICallError as e:
        log.error(f"[GATE 1] Vertex API error for query '{query}': {e}")
        return []
    except Exception as e:
        log.error(f"[GATE 1] Unexpected error for query '{query}': {e}")
        return []


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def run_vertex_search(
    rich_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    GATE 1 — fires all queries from rich_context["queries"] in parallel
    against Vertex AI Search, then deduplicates by URL.

    Args:
        rich_context:  The dict produced by generate_queries().

    Returns:
        Deduplicated list of result dicts:
        [
          {
            "query":   <original search query>,
            "title":   <page title>,
            "url":     <reddit thread URL>,
            "snippet": <text snippet>,
            "doc_id":  <vertex doc id>,
          },
          ...
        ]
    """
    queries: list[str] = rich_context.get("queries", [])

    # TEMP: limit Vertex Search to a single query
    queries = queries[:1]
    if not queries:
        log.warn("[GATE 1] No queries in rich_context — skipping Vertex search.")
        return []

    page_size   = int(settings.DISCOVERY_PAGE_SIZE)
    serving_cfg = _serving_config()
    client      = _build_client()

    log.info(f"[GATE 1] Firing {len(queries)} queries in parallel (page_size={page_size})")

    tasks = [
        _search_one(client, serving_cfg, query, page_size)
        for query in queries
    ]
    nested: list[list[dict]] = await asyncio.gather(*tasks)

    flat: list[dict] = [item for batch in nested for item in batch]

    seen:    set[str]   = set()
    deduped: list[dict] = []
    for item in flat:
        key = hashlib.md5(item["url"].encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    log.info(f"[GATE 1] Complete — {len(flat)} raw → {len(deduped)} unique results")
    return deduped