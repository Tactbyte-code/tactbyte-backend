import runpod
from src.core.settings import settings

log = runpod.RunPodLogger()


async def _handle_playstore_search(query_id: str) -> dict:
    log.info(f"[PLAYSTORE][SEARCH] Starting | query_id={query_id}")
    # TODO
    return {"statusCode": 200}


async def _handle_playstore_summary(query_id: str) -> dict:
    log.info(f"[PLAYSTORE][SUMMARY] Starting | query_id={query_id}")
    # TODO
    return {"statusCode": 200}