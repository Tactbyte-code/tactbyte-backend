import logging
import httpx
from fastapi import HTTPException
from src.core.settings import settings

logger = logging.getLogger(__name__)


async def trigger(query_id: str, service: str, mode: str) -> str:
    """Trigger a RunPod job. Returns the job ID."""

    print(f"Triggering RunPod job for query_id={query_id}, mode={mode}")

    api_key      = settings.RUNPOD_API_KEY
    endpoint_url = settings.RUNPOD_ENDPOINT

    if not api_key or not endpoint_url:
        raise HTTPException(status_code=500, detail="RunPod not configured")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                endpoint_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "input": {
                        "query_id": query_id,
                        "service":  service,
                        "mode":     mode,
                    }
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("RunPod trigger failed", extra={"query_id": query_id, "mode": mode})
        raise HTTPException(status_code=502, detail=f"RunPod error: {e.response.text}")
    except httpx.RequestError as e:
        logger.error("RunPod unreachable", extra={"query_id": query_id, "mode": mode})
        raise HTTPException(status_code=502, detail=f"Failed to reach RunPod: {e}")

    data = response.json()
    return data.get("id")