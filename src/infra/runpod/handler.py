#!/usr/bin/env python3
import runpod
from src.core.settings import settings
from src.infra.runpod.reddit.services import reddit
from src.infra.runpod.playstore.services import playstore
import src.app.registry 

# ─── Router ───────────────────────────────────────────────────────────────────

async def handler(job: dict):
    """
    RunPod serverless handler.
    service: "reddit" | "playstore"
    mode:    "search" | "summary"
    """
    inp      = job.get("input", {})
    service  = inp.get("service")
    mode     = inp.get("mode")
    query_id = inp.get("query_id")

    # log.info(f"Job received | service={service} | mode={mode} | query_id={query_id}")

    # ── validate ──────────────────────────────────────────────────────────────
    if not service:
        return {"statusCode": 400, "body": {"error": "Missing service"}}
    if not mode:
        return {"statusCode": 400, "body": {"error": "Missing mode"}}
    if not query_id:
        return {"statusCode": 400, "body": {"error": "Missing query_id"}}
    if service not in ("reddit", "playstore"):
        return {"statusCode": 400, "body": {"error": f"Unknown service: {service}"}}
    if mode not in ("search", "summary"):
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


runpod.serverless.start({"handler": handler})