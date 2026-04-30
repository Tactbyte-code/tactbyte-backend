from src.infra.runpod.ai_lead_engine.stages.stage_1 import stage_1_prepare
from src.infra.runpod.ai_lead_engine.stages.stage_2 import stage_2_fetch
from src.infra.runpod.ai_lead_engine.stages.stage_3 import stage_3_vector_filter
from src.infra.runpod.ai_lead_engine.stages.stage_4 import stage_4_ai_filter


async def _handle_sync_leads(query_id) -> dict:
    campaign_history_id = int(query_id)
    print(f"[pipeline] Starting campaign_history_id={campaign_history_id}")

    # ── Stage 1: Prepare ───────────────────────────────────────────────────────
    try:
        prepare = await stage_1_prepare(campaign_history_id)
    except ValueError as e:
        return {"statusCode": 400, "body": {"error": str(e)}}

    # ── Stage 2: Fetch + Embed + Save ──────────────────────────────────────────
    fetch = await stage_2_fetch(prepare)

    if not fetch.lead_ids:
        return {
            "statusCode": 200,
            "body": {
                "campaign_id":         fetch.campaign_id,
                "campaign_history_id": fetch.campaign_history_id,
                "leads_saved":         0,
            },
        }

    # ── Stage 3: Vector Filter ─────────────────────────────────────────────────
    vector = await stage_3_vector_filter(fetch)

    if not vector.surviving_lead_ids:
        return {
            "statusCode": 200,
            "body": {
                "campaign_id":         vector.campaign_id,
                "campaign_history_id": vector.campaign_history_id,
                "leads_saved":         0,
                "message":             "All leads filtered out by vector similarity",
            },
        }

    # ── Stage 4: AI Filter ─────────────────────────────────────────────────────
    ai = await stage_4_ai_filter(vector)

    print(f"[pipeline] Done campaign_history_id={campaign_history_id}")

    return {
        "statusCode": 200,
        "body": {
            "campaign_id":         ai.campaign_id,
            "campaign_history_id": ai.campaign_history_id,
            "confirmed":           ai.confirmed_count,
            "rejected":            ai.rejected_count,
        },
    }