"""
generate_context.py  (Stage 2: research plan)
=============================================
Handles RunPod job:  {"service": "validate", "mode": "generate-context", "query_id": ...}
Called by the status router when a ValidateQuery reaches status CREATED.

Flow
----
1. Load the saved ValidateQuery (short DB session).
2. One LLM call (Sarvam via get_client) -> ResearchPlan, validated with Pydantic.
   - tolerant: over-long lists are clipped, not rejected
   - one repair retry for invalid JSON, backoff retries for transient HTTP errors
3. Country code is resolved deterministically from the profile when possible.
4. Save ResearchPlan into ValidateQueryContext and advance the status to
   STATUS_AFTER_PLAN in ONE transaction. The same row is created with an EMPTY
   collection_report ({}), which the search stage fills in later.
5. Return. This handler enqueues NOTHING: the router sees the new status as VALIDATED and
   dispatches the next stage (search) itself.

collection_report
-----------------
Owned by the SEARCH stage, not by this one. After the collectors run, the search handler
writes one entry per collector (status, item count, error, duration) into
ValidateQueryContext.collection_report, so later stages (scoring, summary) can tell
"collector ran and found nothing" from "collector failed" from "collector never ran".
This handler only guarantees that the column exists and starts as {} (= "nothing
collected yet"). It never writes collector results itself.

Recommended DB changes
----------------------
    UNIQUE (query_id) on validate_query_context          (protects against two jobs racing)
    research_plan     = Column(JSONB, nullable=True)
    collection_report = Column(JSONB, nullable=True, server_default=text("'{}'::jsonb"))
    + an Alembic migration adding both columns
Dependencies:  pydantic>=2, sqlalchemy (async), pycountry (optional)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.core.database import AsyncSessionLocal
from src.infra.runpod.llm import get_client
from src.app.validate.model import (
    ValidateQuery,
    ValidateQueryContext,
    ValidateQueryStatus,
    ResearchPlan
)

try:  # optional: deterministic country resolution
    import pycountry
except ImportError:  # pragma: no cover
    pycountry = None

logger = logging.getLogger(__name__)

# The status your router reads to start the NEXT stage. Keep VALIDATED while the
# router maps VALIDATED -> search. Rename to PLANNED only together with the router.
STATUS_AFTER_PLAN = ValidateQueryStatus.VALIDATED

BACKOFF_BASE = 1.0  # seconds between LLM retries; tests set this to 0

_SYSTEM_CONTEXT = (
    "You are an expert venture capitalist and market research analyst. "
    "Your sole job is to analyse startup ventures and generate structured market validation context. "
    "Return ONLY strict, valid JSON. Output MUST start with { and end with }. "
    "Do NOT wrap output in markdown, code fences, or add any explanatory text outside the JSON object."
)

# --------------------------------------------------------------------------- #
# Prompt + parsing
# --------------------------------------------------------------------------- #

# Example of the exact output shape (a DIFFERENT venture, so values are not copied).
# It is validated at import time, so it can never drift from the models above.
_EXAMPLE: dict[str, Any] = {
    "business_type": "physical",
    "country_iso2": "GB",
    "pain": {
        "problem_statement": "Office workers cannot find quick, good coffee near their workplace",
        "target_segment": "office workers in city centres",
        "complaint_queries": ["coffee shop queue too long on lunch break",
                              "no decent coffee near my office",
                              "overpriced coffee in the city centre"],
        "alternative_queries": ["alternatives to Starbucks near offices"],
        "competitor_app_terms": ["Pret", "Costa"],
        "stackexchange_sites": [],
    },
    "market": {
        "industry_keywords": ["coffee shops", "specialty coffee"],
        "indicator_search_terms": ["number of food service enterprises",
                                   "household expenditure on cafes"],
        "institutional_queries": ["UK coffee shop market size OR CAGR -quora -reddit"],
        "bottom_up_variables": ["office workers per district", "average daily coffee spend"],
    },
    "competition": {
        "seed_competitors": ["Pret A Manger", "Costa Coffee"],
        "discovery_queries": ["independent specialty coffee shops city centre"],
        "pricing_queries": ["flat white price UK coffee chains"],
        "osm_tags": ["amenity=cafe"],
    },
    "cost": {
        "cost_items": ["shop rent", "espresso machine", "barista wages", "licences"],
        "wage_roles": ["barista", "shift manager"],
        "licence_queries": ["food business registration UK cost"],
    },
    "risk": {
        "regulatory_queries": ["UK food hygiene registration requirements"],
        "funding_queries": ["small cafe business loans UK"],
        "survival_sector_terms": ["food service", "accommodation and food services"],
    },
    "nlp_anchors": ["specialty coffee", "barista", "footfall", "takeaway"],
    "topic_boundary": {
        "in_scope": ["independent city-centre coffee shops"],
        "adjacent": ["office catering", "coffee subscriptions"],
        "out_of_scope": ["coffee farming", "supermarket coffee brands"],
    },
    "schema_hints": {
        "pricing_models": ["per-cup", "loyalty card"],
        "competitor_names": ["Pret A Manger", "Costa Coffee"],
        "key_metrics": ["average cup price", "daily footfall"],
    },
}
ResearchPlan.model_validate(_EXAMPLE)  # fail fast on drift


def build_prompt(title: str, description: str, industry: str, stage: str,
                 location: str) -> str:
    return f"""Plan desk research to validate the following venture. Return ONE JSON object.

VENTURE
Title: {title}
Description: {description}
Industry: {industry}
Stage: {stage}
Founder location / target region: {location}

RULES
- pain.complaint_queries: plain first-person phrasing the customer would actually write
  (e.g. "struggling to chase late invoices", "why is <incumbent> so frustrating").
  NO search operators and NO negative keywords: forums and reviews are the intended source.
- pain.alternative_queries: e.g. "alternatives to <incumbent>". Only name incumbents you are sure exist.
- market.institutional_queries: Google-style queries aimed at reports, statistics and pricing.
  These MAY use OR and negative keywords such as -quora -reddit -pinterest.
- market.indicator_search_terms: short phrases used to locate official statistical indicators
  (e.g. "number of small enterprises", "household expenditure on restaurants").
- competition.seed_competitors: real, well-known names only. Never invent; leave empty if unsure.
- competition.osm_tags: valid OpenStreetMap key=value tags, ONLY for physical/service/hybrid businesses.
- business_type must be exactly one of: digital, physical, service, hybrid.
- country_iso2: ISO-3166 alpha-2 code (e.g. IN, US, GB) derived from the location; "WW" if global or unclear.
- Keep every list concise (typically 3-6 items). No commentary, no markdown, JSON only.

OUTPUT SHAPE (example for a DIFFERENT venture; do not copy its values):
{json.dumps(_EXAMPLE, indent=1)}"""


def parse_plan(raw: str) -> ResearchPlan:
    cleaned = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?", "", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in LLM response")
    return ResearchPlan.model_validate_json(cleaned[start:end + 1])


_TRANSIENT_HTTP = re.compile(r"^HTTP (429|5\d\d)")


def _is_transient(exc: Exception) -> bool:
    """llm_client._post raises RuntimeError('HTTP <code>...') for HTTP errors and
    lets URLError/timeouts (OSError subclasses) through unchanged."""
    if isinstance(exc, OSError):
        return True
    return isinstance(exc, RuntimeError) and bool(_TRANSIENT_HTTP.match(str(exc)))


async def _generate_plan(llm: Any, prompt: str, max_attempts: int = 4) -> ResearchPlan:
    last_err: str | None = None
    parse_failures = 0
    for attempt in range(1, max_attempts + 1):
        p = prompt if last_err is None else (
            f"{prompt}\n\nYour previous reply was invalid: {last_err}\n"
            "Return the corrected JSON object only.")
        try:
            # llm.call is synchronous (urllib): run it in a worker thread.
            raw = await asyncio.to_thread(llm.call, _SYSTEM_CONTEXT, p)
        except Exception as exc:  # noqa: BLE001
            if _is_transient(exc) and attempt < max_attempts:
                delay = BACKOFF_BASE * 2 ** attempt
                logger.warning("[generate_context] transient LLM error (%s); retry in %.0fs",
                               exc, delay)
                await asyncio.sleep(delay)
                continue
            raise
        try:
            return parse_plan(raw)
        except (ValueError, ValidationError) as exc:
            last_err = str(exc)[:500]
            parse_failures += 1
            logger.warning("[generate_context] invalid plan (parse failure %d): %s",
                           parse_failures, last_err)
            if parse_failures >= 2:
                break
    raise ValueError(f"LLM returned an invalid research plan after retries: {last_err}")


def _resolve_country(raw: str | None) -> str | None:
    """Deterministic country lookup (name, alpha-2 or alpha-3) from the user's profile."""
    if not raw or pycountry is None:
        return None
    try:
        return pycountry.countries.lookup(str(raw).strip()).alpha_2
    except LookupError:
        return None


# --------------------------------------------------------------------------- #
# DB helpers (short-lived sessions; never held across the LLM call)
# --------------------------------------------------------------------------- #

async def _load_query(query_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(
            select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
        if rec is None:
            raise ValueError(f"ValidateQuery with id {query_id} not found.")
        existing = (await db.execute(
            select(ValidateQueryContext.id).where(
                ValidateQueryContext.query_id == query_id))).first()
        loc = (rec.profile or {}).get("location", {}) or {}
        return {
            "title": rec.title, "description": rec.description,
            "industry": rec.industry, "stage": rec.stage,
            "location": loc.get("city") or loc.get("country") or "Global",
            "country": loc.get("country"),
            "has_context": existing is not None,
        }


async def _save_plan(query_id: str, plan: ResearchPlan, provider: str, model: str) -> None:
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(
            select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
        if rec is None:
            raise ValueError(f"ValidateQuery with id {query_id} not found.")
        db.add(ValidateQueryContext(
            query_id=rec.id,
            market_signals=plan.market.institutional_queries,      # legacy column
            nlp_anchors=plan.nlp_anchors,
            topic_boundary=plan.topic_boundary.model_dump(),
            schema_hints=plan.schema_hints.model_dump(),
            research_plan=plan.model_dump(),                       # new JSONB column
            collection_report={},                                  # filled by the search stage
            provider=provider,
            model=model,
        ))
        rec.search_queries = plan.market.institutional_queries     # legacy field
        rec.complete_step(STATUS_AFTER_PLAN)
        try:
            await db.commit()
        except IntegrityError:
            # Two jobs raced; UNIQUE(query_id) rejected the second row. Nothing to do.
            await db.rollback()
            logger.warning("[generate_context] context for %s was already saved by another job",
                           query_id)


async def _mark_failed(query_id: str, message: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            rec = (await db.execute(
                select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
            if rec is not None:
                rec.fail_step(message)
                await db.commit()
    except Exception:  # noqa: BLE001 - never mask the original error
        logger.exception("[generate_context] could not record failure for %s", query_id)


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #

async def _handle_validate_generate_context(query_id: str) -> dict[str, Any]:
    """Stage 2: build and persist the ResearchPlan, then advance the status.
    The status router starts the next stage; this handler enqueues nothing."""
    logger.info("[generate_context] start query_id=%s", query_id)
    try:
        q = await _load_query(query_id)

        if q["has_context"]:
            # Retried job: the plan and status were saved atomically, so nothing is left to do.
            logger.info("[generate_context] context already exists for %s; nothing to do", query_id)
            return {"statusCode": 200, "message": "Research plan already generated"}

        llm = get_client()  # reads provider/model/key/base_url/max_tokens from settings
        prompt = build_prompt(q["title"], q["description"], q["industry"],
                              q["stage"], q["location"])
        plan = await _generate_plan(llm, prompt)
        iso = _resolve_country(q["country"])
        if iso:
            plan.country_iso2 = iso   # deterministic beats the LLM's guess
        await _save_plan(query_id, plan, llm.provider, llm.model)

        logger.info("[generate_context] done query_id=%s", query_id)
        return {"statusCode": 200, "message": "Research plan generated"}

    except Exception as exc:
        logger.exception("[generate_context] failed query_id=%s: %s", query_id, exc)
        await _mark_failed(query_id, str(exc))
        raise