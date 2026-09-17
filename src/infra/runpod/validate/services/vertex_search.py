import asyncio
import hashlib
import json
import logging
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import discoveryengine_v1 as discoveryengine
from google.oauth2 import service_account

from src.core.settings import settings

logger = logging.getLogger(__name__)


def _build_client() -> discoveryengine.SearchServiceAsyncClient:
    creds_info = json.loads(settings.GOOGLE_APPLICATION_CREDENTIALS_JSON)
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
        f"/engines/{settings.DISCOVERY_ENGINE_ID_VALIDATE}"
        f"/servingConfigs/{settings.DISCOVERY_SERVING_CONFIG}"
    )


def _parse_results(
    response: discoveryengine.SearchResponse,
    query: str,
) -> list[dict[str, Any]]:
    results = []
    for result in response.results:
        doc = result.document
        derived = dict(doc.derived_struct_data) if doc.derived_struct_data else {}
        struct = dict(doc.struct_data) if doc.struct_data else {}

        title = derived.get("title") or struct.get("title", "")
        link = derived.get("link") or struct.get("link", "")
        snippets = derived.get("snippets", [{}])

        snippet_text = ""
        if isinstance(snippets, list) and snippets:
            snippet_text = snippets[0].get("snippet", "")

        if not link:
            continue

        results.append({
            "query": query,
            "title": title,
            "url": link,
            "snippet": snippet_text,
            "doc_id": doc.id,
        })
    return results


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
        results = _parse_results(response, query)
        logger.info(f"[_search_one] query='{query}' → {len(results)} results")
        return results
    except GoogleAPICallError as e:
        logger.error(f"[_search_one] Vertex API error for query '{query}': {e}")
        return []
    except Exception as e:
        logger.error(f"[_search_one] Unexpected error for query '{query}': {e}")
        return []


async def run_vertex_search(
    rich_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Fires all search queries in parallel against Vertex AI Search,
    deduplicating the results by URL.
    """
    queries: list[str] = rich_context.get("queries", [])
    if not queries:
        logger.warning("[run_vertex_search] No queries provided in rich_context — skipping search.")
        return []

    page_size = int(settings.DISCOVERY_PAGE_SIZE)
    serving_cfg = _serving_config()
    client = _build_client()

    logger.info(f"[run_vertex_search] Firing {len(queries)} queries in parallel (page_size={page_size})")

    tasks = [
        _search_one(client, serving_cfg, query, page_size)
        for query in queries
    ]
    nested: list[list[dict]] = await asyncio.gather(*tasks)
    flat: list[dict] = [item for batch in nested for item in batch]

    seen: set[str] = set()
    deduped: list[dict] = []
    for item in flat:
        key = hashlib.md5(item["url"].encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    logger.info(f"[run_vertex_search] Complete — {len(flat)} raw → {len(deduped)} unique results")
    return deduped