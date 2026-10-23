"""
validate_search.py  (Stage 3: collect evidence)
===============================================
Replacement for `_handle_validate_search`.  Called by the router when a ValidateQuery
reaches status VALIDATED; on success the status becomes SEARCH_COMPLETED and the router
starts the next stage.

Use it from your existing validate.py module (keeps _handle_validate_summary untouched):
    from .validate_search import _handle_validate_search

What changed (see the review for reasons)
-----------------------------------------
1. Reads the DB, CLOSES the session, collects (slow network work), then writes in a new session.
2. Canonical parameter keys = the keys of the final report JSON:
   pain, market, demand, competition, unit_economics, cost, regulatory, survival_funding, macro.
   Vertex is still called with your legacy names; its output is mapped back.
3. Query building uses every plan section (cost_items, wage_roles, seed competitors, licence
   queries ...) instead of only a few lists.
4. New collectors: market indicators, HN mention trend, Wikipedia pageviews, App Store.
5. Every collector runs guarded (timeout, error capture) and is reported individually:
   collection_report -> ValidateQueryContext.collection_report (JSONB, new column).
6. Accepts collectors that return dicts OR RawEvidenceItem objects; converts retrieved_at to
   datetime; strips NUL characters (PostgreSQL rejects them).
7. Idempotent: skips if already SEARCH_COMPLETED, never re-inserts existing (parameter, url) rows.
8. Uses complete_step / fail_step; zero evidence is a failure, not a success.

Schema additions:
    ValidateQueryContext.collection_report = Column(JSONB, nullable=True)
    recommended: UNIQUE (query_id, parameter, source_url) on validate_query_evidence
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.app.user.model import User
from src.app.validate.model import (
    ValidateQuery,
    ValidateQueryContext,
    ValidateQueryEvidence,
    ValidateQueryStatus,
)
from src.infra.runpod.validate.services.search_collectors import (
    fetch_appstore_reviews,
    fetch_community_discussions,
    fetch_hn_mention_trend,
    fetch_macro_indicators,
    fetch_market_indicators,
    fetch_wikipedia_pageviews,
    resolve_country,
    fetch_vertex_search
)
# <-- adjust: the module that defines fetch_vertex_search (it was not shared for review)
# from src.infra.runpod.validate.services.vertex_search import fetch_vertex_search

logger = logging.getLogger(__name__)

ALL_PARAMETERS = ["pain", "market", "demand", "competition", "unit_economics",
                  "cost", "regulatory", "survival_funding", "macro"]

# canonical key -> the name fetch_vertex_search already understands
VERTEX_NAME = {
    "pain": "pain_point_severity",
    "market": "market_timing_and_size",
    "demand": "demand_signals",
    "competition": "competitive_defensibility",
    "unit_economics": "monetization_viability",
    "cost": "execution_feasibility",
    "regulatory": "feasibility_regulatory",
    "survival_funding": "survival_funding",
}
CANONICAL = {legacy: canon for canon, legacy in VERTEX_NAME.items()}
CANONICAL.update({p: p for p in ALL_PARAMETERS})

MAX_QUERIES = 8              # per parameter
COLLECTOR_TIMEOUT_S = 90.0   # one hung collector must not stall the job
VERTEX_CONCURRENCY = 4
MAX_RAW_CHARS = 20000


# --------------------------------------------------------------------------- #
# Query building
# --------------------------------------------------------------------------- #


def _uniq(items: list[str] | None) -> list[str]:
    seen, out = set(), []
    for s in items or []:
        s = (s or "").strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def build_queries(plan: dict) -> dict[str, list[str]]:
    pain, market = plan.get("pain") or {}, plan.get("market") or {}
    comp, risk = plan.get("competition") or {}, plan.get("risk") or {}
    cost, hints = plan.get("cost") or {}, plan.get("schema_hints") or {}

    country = resolve_country(plan.get("country_iso2"))
    where = "" if country["iso2"] == "WW" else country["name"]
    competitors = _uniq((comp.get("seed_competitors") or []) + (pain.get("competitor_app_terms") or [])
                        + (hints.get("competitor_names") or []))[:5]

    def tag(text: str) -> str:
        return f"{text} {where}".strip()

    q = {
        # complaints and "alternatives to X" phrasing, no operators
        "pain": (pain.get("complaint_queries") or []) + (pain.get("alternative_queries") or []),
        # institutional sizing + indicator lookups + bottom-up variables (sizing inputs, not pricing)
        "market": (market.get("institutional_queries") or []) + (market.get("indicator_search_terms") or [])
                  + (market.get("bottom_up_variables") or []),
        "demand": (market.get("industry_keywords") or []) + (pain.get("complaint_queries") or [])[:3],
        # bare competitor names make poor queries: ask for features/limitations explicitly
        "competition": (comp.get("discovery_queries") or [])
                       + [f"{c} features and limitations" for c in competitors],
        # per-competitor pricing pages feed price_from / pricing_benchmarks
        "unit_economics": (comp.get("pricing_queries") or []) + [tag(f"{c} pricing plans") for c in competitors],
        # licences + every cost item + a salary query per wage role
        "cost": (cost.get("licence_queries") or []) + [tag(f"{i} cost") for i in cost.get("cost_items") or []]
                + [tag(f"{r} average salary") for r in cost.get("wage_roles") or []],
        # licence/registration rules are regulatory facts too
        "regulatory": (risk.get("regulatory_queries") or []) + (cost.get("licence_queries") or []),
        "survival_funding": (risk.get("funding_queries") or [])
                            + [tag(f"{t} business survival rate OR failure rate")
                               for t in risk.get("survival_sector_terms") or []],
    }
    return {k: _uniq(v)[:MAX_QUERIES] for k, v in q.items()}


# --------------------------------------------------------------------------- #
# Guarded collector execution
# --------------------------------------------------------------------------- #


@dataclass
class Job:
    name: str
    factory: Callable[[], Awaitable[list]]
    vertex: bool = False


def build_jobs(plan: dict, queries: dict[str, list[str]]) -> list[Job]:
    market, pain = plan.get("market") or {}, plan.get("pain") or {}
    comp = plan.get("competition") or {}
    country_code = plan.get("country_iso2") or "WW"   # missing country -> world, never a silent default

    industry = market.get("industry_keywords") or []
    anchors = [a for a in (plan.get("nlp_anchors") or []) if " " in a]
    trend_queries = _uniq(industry + anchors)[:4]
    app_terms = _uniq((pain.get("competitor_app_terms") or []) + (comp.get("seed_competitors") or []))[:4]

    jobs = [
        Job("worldbank_macro", lambda: fetch_macro_indicators(country_code)),
        Job("worldbank_market", lambda: fetch_market_indicators(country_code)),
        Job("hn_pain", lambda: fetch_community_discussions("pain", queries["pain"])),
        Job("hn_demand", lambda: fetch_community_discussions("demand", queries["demand"])),
        Job("hn_trend", lambda: fetch_hn_mention_trend("demand", trend_queries)),
        Job("wikipedia_pageviews", lambda: fetch_wikipedia_pageviews("demand", industry)),
    ]
    if plan.get("business_type") in ("digital", "hybrid") and app_terms:
        jobs.append(Job("appstore", lambda: fetch_appstore_reviews(app_terms, country_code)))

    for param, name in VERTEX_NAME.items():
        qs = queries.get(param) or []
        if qs:
            jobs.append(Job(f"vertex_{param}", (lambda n=name, p=param, qs=qs: _vertex(n, p, qs)), vertex=True))
    return jobs


async def _vertex(legacy_name: str, canonical: str, queries: list[str]) -> list:
    items = await fetch_vertex_search(legacy_name, queries)
    out = []
    for it in items or []:
        d = _as_dict(it)
        d["parameter"] = canonical      # vertex returns the legacy name; store the canonical one
        out.append(d)
    return out


def _as_dict(item: Any) -> dict:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "to_dict"):
        return item.to_dict()
    raise TypeError(f"unsupported evidence item type: {type(item).__name__}")


async def _run_job(job: Job, vertex_sem: asyncio.Semaphore) -> tuple[list[dict], dict]:
    report = {"collector": job.name, "status": "ok", "items": 0, "error": None, "seconds": 0.0}
    t0 = time.monotonic()
    items: list[dict] = []
    try:
        async def call() -> list:
            return await asyncio.wait_for(job.factory(), timeout=COLLECTOR_TIMEOUT_S)

        if job.vertex:
            async with vertex_sem:
                raw = await call()
        else:
            raw = await call()
        items = [_as_dict(i) for i in (raw or [])]
        report["items"] = len(items)
        if not items:
            report["status"] = "empty"
    except asyncio.TimeoutError:
        report.update(status="timeout", error=f"exceeded {COLLECTOR_TIMEOUT_S:.0f}s")
        logger.error("[search] collector %s timed out", job.name)
    except Exception as exc:  # noqa: BLE001 - one collector must never fail the run
        report.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        logger.error("[search] collector %s failed: %s", job.name, exc)
    report["seconds"] = round(time.monotonic() - t0, 2)
    return items, report


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


def _clean(value: Any) -> Any:
    """PostgreSQL rejects NUL (\\x00) in text and JSONB."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt   # naive UTC


def normalise(item: dict) -> dict | None:
    param = CANONICAL.get(item.get("parameter") or "")
    url, content = item.get("source_url"), item.get("raw_content")
    if not param or not url or not content or not item.get("source_type"):
        return None
    return {
        "parameter": param, "source_type": item["source_type"], "source_url": url,
        "title": _clean(item.get("title")), "raw_content": _clean(content)[:MAX_RAW_CHARS],
        "metadata": _clean(item.get("metadata") or {}),
        "retrieved_at": _to_dt(item.get("retrieved_at")),
    }


# --------------------------------------------------------------------------- #
# DB phases
# --------------------------------------------------------------------------- #


def _sv(status: Any) -> Any:
    return getattr(status, "value", status)


async def _load(query_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
        ctx = (await db.execute(
            select(ValidateQueryContext).where(ValidateQueryContext.query_id == query_id))).scalars().first()
        if not rec or not ctx:
            raise ValueError(f"Missing records for query {query_id} to proceed with Stage 3.")
        existing = (await db.execute(
            select(ValidateQueryEvidence.parameter, ValidateQueryEvidence.source_url)
            .where(ValidateQueryEvidence.query_id == query_id))).all()
        return {"plan": dict(ctx.research_plan or {}), "status": getattr(rec, "status", None),
                "existing": {f"{p}:{u}" for p, u in existing}}


async def _save(query_id: str, rows: list[dict], report: dict) -> None:
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
        ctx = (await db.execute(
            select(ValidateQueryContext).where(ValidateQueryContext.query_id == query_id))).scalars().first()
        if rec is None:
            raise ValueError(f"ValidateQuery {query_id} disappeared before the save step.")
        if rows:
            db.add_all([ValidateQueryEvidence(
                query_id=rec.id, parameter=r["parameter"], source_type=r["source_type"],
                source_url=r["source_url"], title=r["title"], raw_content=r["raw_content"],
                metadata_=r["metadata"], retrieved_at=r["retrieved_at"]) for r in rows])
        if ctx is not None and hasattr(ValidateQueryContext, "collection_report"):
            ctx.collection_report = report
        else:
            logger.warning("[search] collection_report column missing; report not persisted")
        rec.complete_step(ValidateQueryStatus.SEARCH_COMPLETED)
        await db.commit()


async def _mark_failed(query_id: str, message: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
            if rec is not None:
                rec.fail_step(message)
                await db.commit()
    except Exception:  # noqa: BLE001 - never mask the original error
        logger.exception("[search] could not record failure for %s", query_id)


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #


async def _handle_validate_search(query_id: str) -> dict:
    logger.info("[_handle_validate_search] start query_id=%s", query_id)
    t0 = time.monotonic()
    try:
        state = await _load(query_id)                     # session closed here
        if _sv(state["status"]) == _sv(ValidateQueryStatus.SEARCH_COMPLETED):
            logger.info("[_handle_validate_search] %s already completed; skipping", query_id)
            return {"statusCode": 200, "query_id": query_id, "skipped": True}

        plan = state["plan"]
        queries = build_queries(plan)
        jobs = build_jobs(plan, queries)
        logger.info("[_handle_validate_search] dispatching %d collectors", len(jobs))

        vertex_sem = asyncio.Semaphore(VERTEX_CONCURRENCY)
        results = await asyncio.gather(*(_run_job(j, vertex_sem) for j in jobs))

        rows, seen = [], set(state["existing"])
        dropped = duplicates = 0
        for items, _ in results:
            for raw in items:
                row = normalise(raw)
                if row is None:
                    dropped += 1
                    continue
                key = f"{row['parameter']}:{row['source_url']}"
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                rows.append(row)

        by_param: dict[str, dict] = {p: {"items": 0, "by_source_type": {}} for p in ALL_PARAMETERS}
        for r in rows:
            slot = by_param[r["parameter"]]
            slot["items"] += 1
            slot["by_source_type"][r["source_type"]] = slot["by_source_type"].get(r["source_type"], 0) + 1
        for key in state["existing"]:                      # rows from an earlier partial run
            p = key.split(":", 1)[0]
            if p in by_param:
                by_param[p]["items"] += 1

        collectors = [rep for _, rep in results]
        total = len(rows) + len(state["existing"])
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.monotonic() - t0, 1),
            "collectors": collectors,
            "by_parameter": by_param,
            "parameters_empty": [p for p in ALL_PARAMETERS if by_param[p]["items"] == 0],
            "dropped_invalid": dropped, "duplicates_skipped": duplicates,
            "evidence_total": total,
        }
        if total == 0:
            failed = "; ".join(f"{c['collector']}={c['status']}" for c in collectors)
            raise RuntimeError(f"No evidence could be collected ({failed})")

        await _save(query_id, rows, report)               # new short session
        logger.info("[_handle_validate_search] saved %d new evidence rows for %s", len(rows), query_id)
        return {
            "statusCode": 200, "query_id": query_id, "evidence_count": total, "new_rows": len(rows),
            "parameters_covered": [p for p in ALL_PARAMETERS if by_param[p]["items"] > 0],
            "parameters_empty": report["parameters_empty"],
            "failed_collectors": [c["collector"] for c in collectors if c["status"] in ("error", "timeout")],
        }

    except Exception as exc:
        logger.exception("[_handle_validate_search] failed query_id=%s: %s", query_id, exc)
        await _mark_failed(query_id, str(exc))
        raise