#!/usr/bin/env python3
import os
import base64
import tempfile
import runpod
from src.core.settings import settings
from src.infra.runpod.reddit.services import reddit
from src.infra.runpod.playstore.services import playstore
from src.infra.runpod.validate.services import validate
from src.infra.runpod.validate.services import validate_context
from src.infra.runpod.validate.services import validate_search
from src.infra.runpod.validate.services import validate_filter
from src.infra.runpod.validate.services import validate_extract
from src.infra.runpod.validate.services import validate_score
from src.infra.runpod.validate.services import validate_summary
# import src.app.registry 
# from src.infra.runpod.ai_lead_engine.services import ai_lead_engine

# Decode the GCP key and set the credential path for the container
if "GCP_KEY_B64" in os.environ and "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "wb") as f:
        f.write(base64.b64decode(os.environ["GCP_KEY_B64"]))
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path

# ─── Router ───────────────────────────────────────────────────────────────────

async def handler(job: dict):
    """
    RunPod serverless handler.
    service: "reddit" | "playstore" | "ai-lead-engine" | "validate"
    mode:    "search" | "summary"   | "sync-leads"  |  "generate-context" | "filter" | "extract" | "score"
    """
    inp      = job.get("input", {})
    service  = inp.get("service")
    mode     = inp.get("mode")
    query_id = inp.get("query_id")

    # ──────────────── validate ────────────────
    if not service:
        return {"statusCode": 400, "body": {"error": "Missing service"}}
    if not mode:
        return {"statusCode": 400, "body": {"error": "Missing mode"}}
    if not query_id:
        return {"statusCode": 400, "body": {"error": "Missing query_id"}}
    if service not in ("reddit", "playstore", "ai-lead-engine", "validate"):
        return {"statusCode": 400, "body": {"error": f"Unknown service: {service}"}}
    if mode not in ("search", "summary", "sync-leads", "generate-context", "filter", "extract", "score"):
        return {"statusCode": 400, "body": {"error": f"Unknown mode: {mode}"}}

    # ────────────────────── route ──────────────────────
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
    
    if service == "validate":
            if mode == "generate-context":
                return await validate_context._handle_validate_generate_context(query_id)
            if mode == "search":
                return await validate_search._handle_validate_search(query_id)
            if mode == "filter":
                return await validate_filter._handle_validate_filter(query_id)
            if mode == "extract":
                return await validate_extract._handle_validate_extract(query_id)
            if mode == "score":
                return await validate_score._handle_validate_score(query_id)
            if mode == "summary":
                return await validate_summary._handle_validate_summary(query_id)

    # if service == "ai-lead-engine":
    #     if mode == "sync-leads":
    #         return await ai_lead_engine._handle_sync_leads(query_id)


runpod.serverless.start({"handler": handler})