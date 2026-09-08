#!/usr/bin/env python3
import runpod
from src.core.settings import settings
from src.infra.runpod.reddit.services import reddit
from src.infra.runpod.playstore.services import playstore
import src.app.registry 
# from src.infra.runpod.ai_lead_engine.services import ai_lead_engine

# ─── Router ───────────────────────────────────────────────────────────────────

async def handler(job: dict):
    """
    RunPod serverless handler.
    service: "reddit" | "playstore" | "ai-lead-engine"
    mode:    "search" | "summary"   | "sync-leads"
    """
    inp      = job.get("input", {})
    service  = inp.get("service")
    mode     = inp.get("mode")
    query_id = inp.get("query_id")

    # ── validate ──────────────────────────────────────────────────────────────
    if not service:
        return {"statusCode": 400, "body": {"error": "Missing service"}}
    if not mode:
        return {"statusCode": 400, "body": {"error": "Missing mode"}}
    if not query_id:
        return {"statusCode": 400, "body": {"error": "Missing query_id"}}
    if service not in ("reddit", "playstore", "ai-lead-engine"):
        return {"statusCode": 400, "body": {"error": f"Unknown service: {service}"}}
    if mode not in ("search", "summary", "sync-leads"):
        return {"statusCode": 400, "body": {"error": f"Unknown mode: {mode}"}}

    # ── route ─────────────────────────────────────────────────────────────────
    if service == "reddit":
        if mode == "search":
            return await reddit._handle_reddit_search(query_id)
        if mode == "summary":
            return await reddit._handle_reddit_summary(query_id)

    if service == "playstore":
        if mode == "search":
            return await playstore._handle_playstore_search(query_id)
        if mode == "summary":
            return await playstore._handle_playstore_summary(query_id)

    # if service == "ai-lead-engine":
    #     if mode == "sync-leads":
    #         return await ai_lead_engine._handle_sync_leads(query_id)


runpod.serverless.start({"handler": handler})