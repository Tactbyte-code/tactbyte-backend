"""
validate_filter.py  (Stage 4: clean and filter)
===============================================
Job:  {"service": "validate", "mode": "filter", "query_id": ...}
Status: SEARCH_COMPLETED -> FILTERED          (no LLM; embedding model only)

Use it from your existing validate.py module:
    from .validate_filter import _handle_validate_filter

Reads   validate_query_evidence  (parameter, source_type, source_url, title, raw_content,
                                  metadata_, id)  and  validate_query_context.research_plan
Writes  validate_query_evidence.is_selected / relevance_score / filter_meta  (every row)
        validate_query_context.filter_report                                  (counts + calibration stats)
        validate_query.status = FILTERED

FORMULAS (all per evidence item i of parameter p)
-------------------------------------------------
text_i        = title + ". " + raw_content, first EMBED_CHARS characters
cos_i         = e_i . r_p          (L2-normalised vectors; r_p = embedding of the parameter's reference text)
anchor_hits_i = number of DISTINCT nlp_anchors found in text_i (case-insensitive, plural/hyphen tolerant)
a_i           = min(1, anchor_hits_i / 2)
q_i           = min(1, ln(1 + points + comments + likes) / ln(1 + 100))        (engagement; 0 if absent)
out_sim_i     = max over out_of_scope phrases of cos(e_i, phrase)
keep_sim_i    = max over in_scope and adjacent phrases of cos(e_i, phrase)
margin_i      = out_sim_i - keep_sim_i
rank_i        = 0.70 * clip(cos_i, 0, 1) + 0.20 * a_i + 0.10 * q_i

DROP RULES, in this order
  structured sources (World Bank, trends)  -> always kept, never embedded
  short          : fewer than 40 characters or 6 words
  duplicate      : same normalised text (first 400 chars) within the parameter; keep highest (engagement, length)
  near_duplicate : cos(e_i, e_j) >= 0.95 with an already kept item of the same parameter
  out_of_scope   : (margin_i >= 0.05 and out_sim_i >= 0.30)  OR  (an out_of_scope phrase appears verbatim and no anchor hit)
                   applied only to pain, demand, competition, unit_economics
  low_similarity : cos_i < floor_p
  no_anchor      : anchors exist, anchor_hits_i = 0, and cos_i < floor_p + 0.08      (anchors are a soft gate)
  over_cap       : not in the top cap_p by rank_i (max 60% of the cap from one source_type)
All thresholds are STARTING VALUES: they depend on the embedding model. Calibrate with
filter_report.by_parameter[p].sim_p10 / sim_median / sim_p90.

Dependencies: numpy; sentence-transformers + einops (local provider) or google-genai (vertex provider)
Schema additions:
    validate_query_evidence: is_selected BOOLEAN, relevance_score FLOAT, filter_meta JSONB
    validate_query_context : filter_report JSONB
    ValidateQueryStatus    : FILTERED   (ALTER TYPE ... ADD VALUE if it is a native Postgres enum)
Env/settings: EMBEDDING_PROVIDER = local | vertex (default local); EMBEDDING_MODEL (optional)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from sqlalchemy import select, update

from src.core.database import AsyncSessionLocal
from src.core.settings import settings
from src.app.validate.model import (
    ValidateQuery,
    ValidateQueryContext,
    ValidateQueryEvidence,
    ValidateQueryStatus,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuration (starting values; calibrate per embedding model)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ParamCfg:
    floor: float        # minimum cosine similarity to the parameter reference
    cap: int            # maximum items passed on to Stage 5 (LLM)
    min_selected: int   # below this the parameter is flagged "thin"


FILTER_CONFIG: dict[str, ParamCfg] = {
    "pain":             ParamCfg(0.30, 150, 10),
    "demand":           ParamCfg(0.28, 60, 5),
    "market":           ParamCfg(0.28, 40, 3),
    "competition":      ParamCfg(0.30, 50, 3),
    "unit_economics":   ParamCfg(0.30, 40, 3),
    "cost":             ParamCfg(0.28, 40, 3),
    "regulatory":       ParamCfg(0.30, 30, 2),
    "survival_funding": ParamCfg(0.25, 30, 0),   # structurally sparse with free sources
    "macro":            ParamCfg(0.0, 50, 0),
}
DEFAULT_CFG = ParamCfg(0.30, 40, 0)
ALL_PARAMETERS = list(FILTER_CONFIG)

STRUCTURED_SOURCE_TYPES = {"dbnomics", "worldbank_api", "hn_trend", "wikipedia_pageviews"}
BOUNDARY_PARAMS = {"pain", "demand", "competition", "unit_economics"}   # segment-sensitive parameters

MIN_CHARS, MIN_WORDS, EMBED_CHARS = 40, 6, 1200
NEAR_DUP_COS = 0.95
ANCHOR_PENALTY, ANCHORS_SATURATE = 0.08, 2
BOUNDARY_MARGIN, BOUNDARY_MIN_OUT = 0.05, 0.30
MAX_SOURCE_SHARE = 0.60
W_SIM, W_ANCHOR, W_ENG, ENG_SATURATE = 0.70, 0.20, 0.10, 100


# --------------------------------------------------------------------------- #
# Embedders (queries and documents are embedded differently by some models)
# --------------------------------------------------------------------------- #


class Embedder(Protocol):
    name: str

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...
    def embed_documents(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Local model inside the RunPod worker. Default: nomic-embed-text-v1.5, which needs the
    'search_query:' / 'search_document:' prefixes and `pip install einops`."""

    def __init__(self, model_name: str, device: str | None = None):
        from sentence_transformers import SentenceTransformer
        self.name = model_name
        self.model = SentenceTransformer(model_name, trust_remote_code=True, device=device)
        self.model.max_seq_length = min(int(getattr(self.model, "max_seq_length", 512) or 512), 512)
        nomic = "nomic" in model_name.lower()
        self._qp, self._dp = ("search_query: ", "search_document: ") if nomic else ("", "")

    def _enc(self, texts: list[str], prefix: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        return np.asarray(self.model.encode([prefix + t for t in texts], batch_size=32,
                                            normalize_embeddings=True, show_progress_bar=False),
                          dtype=np.float32)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._enc(texts, self._qp)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._enc(texts, self._dp)


class VertexEmbedder:
    """Vertex AI embeddings through google-genai (reads project and location from settings)."""

    def __init__(self, model_name: str = "text-embedding-005"):
        from google import genai
        from google.genai import types
        self.name, self._types = model_name, types
        
        # Pulling authentication and routing parameters directly from your Pydantic settings
        self.client = genai.Client(
            vertexai=True, 
            project=settings.GOOGLE_CLOUD_PROJECT,
            location=getattr(settings, "GOOGLE_CLOUD_LOCATION", "us-central1")
        )

    def _enc(self, texts: list[str], task: str) -> np.ndarray:
        vecs: list[list[float]] = []
        for i in range(0, len(texts), 100):
            r = self.client.models.embed_content(
                model=self.name, contents=texts[i:i + 100],
                config=self._types.EmbedContentConfig(task_type=task))
            vecs.extend(e.values for e in r.embeddings)
        return np.asarray(vecs, dtype=np.float32) if vecs else np.zeros((0, 1), dtype=np.float32)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._enc(texts, "RETRIEVAL_QUERY")

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._enc(texts, "RETRIEVAL_DOCUMENT")


_EMBEDDER: Embedder | None = None


def get_embedder() -> Embedder:
    """One instance per worker process, so the model stays loaded between jobs."""
    global _EMBEDDER
    if _EMBEDDER is None:
        provider = (getattr(settings, "EMBEDDING_PROVIDER", None) or os.getenv("EMBEDDING_PROVIDER") or "local").lower()
        model = getattr(settings, "EMBEDDING_MODEL", None) or os.getenv("EMBEDDING_MODEL")
        _EMBEDDER = (VertexEmbedder(model or "text-embedding-005") if provider == "vertex"
                     else SentenceTransformerEmbedder(model or "nomic-ai/nomic-embed-text-v1.5"))
        logger.info("[filter] embedder ready: %s (%s)", _EMBEDDER.name, provider)
    return _EMBEDDER


# --------------------------------------------------------------------------- #
# Text utilities
# --------------------------------------------------------------------------- #


def norm_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def content_hash(s: str) -> str:
    return hashlib.sha1(norm_text(s)[:400].encode()).hexdigest()


def compile_phrases(phrases: list[str]) -> list[tuple[str, re.Pattern]]:
    """Case-insensitive, hyphen/space tolerant, plural tolerant whole-phrase patterns."""
    out = []
    for ph in phrases or []:
        words = re.findall(r"\w+", (ph or "").lower())
        if words:
            body = r"[\s\-_/]+".join(re.escape(w) for w in words)
            out.append((ph, re.compile(rf"(?<!\w){body}s?(?!\w)", re.I)))
    return out


def engagement(meta: dict | None) -> float:
    total = 0.0
    for k in ("points", "num_comments", "likes", "like_count"):
        v = (meta or {}).get(k)
        if isinstance(v, (int, float)) and v > 0:
            total += v
    return total


def _unit(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    if m.size == 0:
        return m
    return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)


# --------------------------------------------------------------------------- #
# Reference texts and topic boundary (from research_plan)
# --------------------------------------------------------------------------- #


def _j(items: list[str] | None, n: int = 6) -> str:
    return ", ".join([i for i in (items or []) if i][:n])


def build_reference_texts(plan: dict) -> dict[str, str]:
    """One reference per parameter: an item is compared with ITS parameter's reference, because
    a regulatory page is never close to a complaint sentence, yet may be exactly what is needed."""
    pain, market = plan.get("pain") or {}, plan.get("market") or {}
    comp, cost = plan.get("competition") or {}, plan.get("cost") or {}
    risk = plan.get("risk") or {}
    ps = (pain.get("problem_statement") or "").strip()
    seg = (pain.get("target_segment") or "").strip()
    base = f"{ps} {seg}".strip() or _j(market.get("industry_keywords")) or "startup market research"
    refs = {
        "pain": f"{base}. Complaints: {_j(pain.get('complaint_queries'), 4)}",
        "demand": f"Demand and growing interest for: {base}. Topics: {_j(market.get('industry_keywords'))}",
        "market": f"Market size, number of users and growth for: {_j((market.get('industry_keywords') or []) + (market.get('indicator_search_terms') or []))}",
        "competition": f"Products and competitors for: {base}. {_j((comp.get('seed_competitors') or []) + (comp.get('discovery_queries') or []))}",
        "unit_economics": f"Pricing plans and subscription cost of: {_j((comp.get('seed_competitors') or []) + (comp.get('pricing_queries') or []))}",
        "cost": f"Cost of building and running: {_j((cost.get('cost_items') or []) + (cost.get('wage_roles') or []) + (cost.get('licence_queries') or []))}",
        "regulatory": f"Regulations and compliance requirements: {_j((risk.get('regulatory_queries') or []) + (cost.get('licence_queries') or []))}",
        "survival_funding": f"Funding and startup survival: {_j((risk.get('funding_queries') or []) + (risk.get('survival_sector_terms') or []))}",
    }
    return {p: (t if t.split(":", 1)[-1].strip(" .,") else base) for p, t in refs.items()}


def boundary_phrases(plan: dict) -> tuple[list[str], list[str], list[str]]:
    tb = plan.get("topic_boundary") or {}
    g = lambda k: [x for x in (tb.get(k) or []) if x]  # noqa: E731
    return g("in_scope"), g("adjacent"), g("out_of_scope")


# --------------------------------------------------------------------------- #
# Core filter (pure function: no DB, easy to test)
# --------------------------------------------------------------------------- #


@dataclass
class Row:
    id: Any
    parameter: str
    source_type: str
    source_url: str
    title: str | None
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Decision:
    id: Any
    selected: bool
    score: float | None
    reason: str
    meta: dict = field(default_factory=dict)


@dataclass
class _Cand:
    row: Row
    text: str
    hash: str
    eng: float
    prio: tuple


def _full_text(r: Row) -> str:
    t, body = (r.title or "").strip(), (r.text or "").strip()
    return body if (not t or body.lower().startswith(t.lower())) else f"{t}. {body}"


def _select_with_diversity(items: list[tuple], cap: int, share: float) -> list[tuple]:
    """items: [(rank, cand, meta)] sorted by rank desc. At most `share` of the cap per
    source_type while other types still have candidates; leftover slots are back-filled."""
    types = {c.row.source_type for _, c, _ in items}
    limit = cap if len(types) < 2 else max(1, math.ceil(cap * share))
    chosen, skipped, used = [], [], Counter()
    for it in items:
        t = it[1].row.source_type
        if len(chosen) < cap and used[t] < limit:
            chosen.append(it)
            used[t] += 1
        else:
            skipped.append(it)
    for it in skipped:
        if len(chosen) >= cap:
            break
        chosen.append(it)
    return chosen


def run_filter(rows: list[Row], plan: dict, embedder: Embedder,
               cfg: dict[str, ParamCfg] | None = None) -> tuple[list[Decision], dict]:
    cfg = cfg or FILTER_CONFIG
    t0 = time.monotonic()
    counts: dict[str, Counter] = defaultdict(Counter)
    decisions: dict[Any, Decision] = {}

    def drop(r: Row, reason: str, **meta: Any) -> None:
        decisions[r.id] = Decision(r.id, False, None, reason, meta)
        counts[r.parameter][reason] += 1

    # 1. structured bypass + short filter
    cands: list[_Cand] = []
    for r in rows:
        counts[r.parameter]["collected"] += 1
        if r.source_type in STRUCTURED_SOURCE_TYPES:
            decisions[r.id] = Decision(r.id, True, 1.0, "structured", {"source_type": r.source_type})
            counts[r.parameter]["structured"] += 1
            counts[r.parameter]["selected"] += 1
            continue
        full = _full_text(r)
        norm = norm_text(full)
        if len(norm) < MIN_CHARS or len(norm.split()) < MIN_WORDS:
            drop(r, "short")
            continue
        eng = engagement(r.metadata)
        cands.append(_Cand(r, full[:EMBED_CHARS], content_hash(full), eng, (eng, len(full))))

    # 2. exact duplicates within a parameter (keep the best by engagement, then length)
    best: dict[tuple[str, str], _Cand] = {}
    for c in sorted(cands, key=lambda c: c.prio, reverse=True):
        key = (c.row.parameter, c.hash)
        if key in best:
            drop(c.row, "duplicate", duplicate_of=str(best[key].row.id))
        else:
            best[key] = c
    cands = [c for c in cands if best.get((c.row.parameter, c.hash)) is c]

    sims_by_param: dict[str, list[float]] = defaultdict(list)
    if cands:
        # 3. embeddings
        D = _unit(embedder.embed_documents([c.text for c in cands]))
        refs = build_reference_texts(plan)
        ref_names = list(refs)
        ref_vec = dict(zip(ref_names, _unit(embedder.embed_queries([refs[p] for p in ref_names]))))
        in_ph, adj_ph, out_ph = boundary_phrases(plan)
        phrases = in_ph + adj_ph + out_ph
        B = _unit(embedder.embed_queries(phrases)) if phrases else None
        keep_idx = list(range(len(in_ph) + len(adj_ph)))
        out_idx = list(range(len(in_ph) + len(adj_ph), len(phrases)))
        anchors = compile_phrases(plan.get("nlp_anchors") or [])
        out_pats = [p for _, p in compile_phrases(out_ph)]

        # 4. near-duplicates (embedding similarity), per parameter
        by_param: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(cands):
            by_param[c.row.parameter].append(i)
        alive: list[int] = []
        for p, idxs in by_param.items():
            kept: list[int] = []
            for i in sorted(idxs, key=lambda i: cands[i].prio, reverse=True):
                if kept and float(np.max(D[kept] @ D[i])) >= NEAR_DUP_COS:
                    drop(cands[i].row, "near_duplicate")
                else:
                    kept.append(i)
            alive.extend(kept)

        # 5. relevance, anchors, boundary, floor
        passing: dict[str, list[tuple]] = defaultdict(list)
        for i in sorted(alive):
            c, p = cands[i], cands[i].row.parameter
            pc = cfg.get(p, DEFAULT_CFG)
            s = float(D[i] @ ref_vec[p]) if p in ref_vec else 0.0
            sims_by_param[p].append(s)
            hits = [a for a, pat in anchors if pat.search(c.text)]
            a_score = min(1.0, len(hits) / ANCHORS_SATURATE) if anchors else 0.0
            q = min(1.0, math.log1p(c.eng) / math.log1p(ENG_SATURATE))
            meta: dict[str, Any] = {"similarity": round(s, 4), "anchor_hits": hits,
                                    "source_type": c.row.source_type, "engagement": c.eng,
                                    "content_hash": c.hash}

            if p in BOUNDARY_PARAMS and B is not None and out_idx:
                out_sim = float(np.max(B[out_idx] @ D[i]))
                keep_sim = float(np.max(B[keep_idx] @ D[i])) if keep_idx else 0.0
                margin = out_sim - keep_sim
                meta.update(out_sim=round(out_sim, 4), keep_sim=round(keep_sim, 4), boundary_margin=round(margin, 4))
                lexical_out = any(pat.search(c.text) for pat in out_pats)
                if (margin >= BOUNDARY_MARGIN and out_sim >= BOUNDARY_MIN_OUT) or (lexical_out and not hits):
                    drop(c.row, "out_of_scope", **meta)
                    continue
            if s < pc.floor:
                drop(c.row, "low_similarity", **meta)
                continue
            if anchors and not hits and s < pc.floor + ANCHOR_PENALTY:
                drop(c.row, "no_anchor", **meta)
                continue
            rank = W_SIM * min(max(s, 0.0), 1.0) + W_ANCHOR * a_score + W_ENG * q
            passing[p].append((rank, c, meta))

        # 6. rank, cap, source diversity
        for p, items in passing.items():
            items.sort(key=lambda t: t[0], reverse=True)
            chosen = _select_with_diversity(items, cfg.get(p, DEFAULT_CFG).cap, MAX_SOURCE_SHARE)
            chosen.sort(key=lambda t: t[0], reverse=True)
            chosen_ids = {id(t[1]) for t in chosen}
            for pos, (rank, c, meta) in enumerate(chosen, 1):
                decisions[c.row.id] = Decision(c.row.id, True, round(rank, 4), "selected",
                                               {**meta, "rank_position": pos})
                counts[p]["selected"] += 1
            for rank, c, meta in items:
                if id(c) not in chosen_ids:
                    drop(c.row, "over_cap", rank=round(rank, 4), **meta)

    # 7. report
    src_selected = Counter(r.source_type for r in rows if decisions[r.id].selected)
    by_parameter: dict[str, dict] = {}
    for p in sorted(set(counts) | set(ALL_PARAMETERS)):
        c = counts[p]
        collected = c["collected"]
        after_dedupe = collected - c["short"] - c["duplicate"] - c["near_duplicate"]
        text_selected = c["selected"] - c["structured"]
        sims = sims_by_param.get(p) or []
        entry = {
            "collected": collected, "after_dedupe": after_dedupe, "selected": c["selected"],
            "dropped": {k: c[k] for k in ("short", "duplicate", "near_duplicate", "out_of_scope",
                                          "low_similarity", "no_anchor", "over_cap") if c[k]},
            "structured": c["structured"],
            "thin": bool(collected) and text_selected < cfg.get(p, DEFAULT_CFG).min_selected,
        }
        if sims:
            entry.update(sim_p10=round(float(np.percentile(sims, 10)), 3),
                         sim_median=round(float(np.median(sims)), 3),
                         sim_p90=round(float(np.percentile(sims, 90)), 3))
        by_parameter[p] = entry
    report = {
        "embedding_model": getattr(embedder, "name", "unknown"),
        "duration_seconds": round(time.monotonic() - t0, 1),
        "totals": {"collected": sum(v["collected"] for v in by_parameter.values()),
                   "after_dedupe": sum(v["after_dedupe"] for v in by_parameter.values()),
                   "after_filter": sum(v["selected"] for v in by_parameter.values())},
        "by_parameter": by_parameter,
        "selected_by_source_type": dict(src_selected),
        "thin_parameters": [p for p, v in by_parameter.items() if v["thin"]],
        "thresholds": {p: {"floor": c.floor, "cap": c.cap} for p, c in cfg.items()},
    }
    return [decisions[r.id] for r in rows], report


# --------------------------------------------------------------------------- #
# DB phases + handler
# --------------------------------------------------------------------------- #


def _sv(status: Any) -> Any:
    return getattr(status, "value", status)


def _require_schema() -> Any:
    missing = [c for c in ("is_selected", "relevance_score", "filter_meta")
               if not hasattr(ValidateQueryEvidence, c)]
    if missing:
        raise RuntimeError(f"validate_query_evidence is missing columns {missing}; add them (see module docstring).")
    filtered = getattr(ValidateQueryStatus, "FILTERED", None)
    if filtered is None:
        raise RuntimeError("ValidateQueryStatus.FILTERED is missing; add it (ALTER TYPE ... ADD VALUE if native enum).")
    return filtered


async def _load(query_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
        ctx = (await db.execute(
            select(ValidateQueryContext).where(ValidateQueryContext.query_id == query_id))).scalars().first()
        if not rec or not ctx:
            raise ValueError(f"Missing records for query {query_id} to proceed with Stage 4.")
        plan = dict(ctx.research_plan or {})
        plan.setdefault("nlp_anchors", list(getattr(ctx, "nlp_anchors", None) or []))     # legacy fallbacks
        plan.setdefault("topic_boundary", dict(getattr(ctx, "topic_boundary", None) or {}))
        ev = (await db.execute(
            select(ValidateQueryEvidence).where(ValidateQueryEvidence.query_id == query_id))).scalars().all()
        rows = [Row(id=e.id, parameter=e.parameter, source_type=e.source_type, source_url=e.source_url,
                    title=e.title, text=e.raw_content or "", metadata=dict(e.metadata_ or {})) for e in ev]
        return {"plan": plan, "status": getattr(rec, "status", None), "rows": rows}


async def _save(query_id: str, filtered_status: Any, decisions: list[Decision], report: dict) -> None:
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
        ctx = (await db.execute(
            select(ValidateQueryContext).where(ValidateQueryContext.query_id == query_id))).scalars().first()
        if rec is None:
            raise ValueError(f"ValidateQuery {query_id} disappeared before the save step.")
        mappings = [{"id": d.id, "is_selected": d.selected, "relevance_score": d.score,
                     "filter_meta": {"reason": d.reason, **d.meta}} for d in decisions]
        for i in range(0, len(mappings), 500):          # ORM bulk UPDATE by primary key
            await db.execute(update(ValidateQueryEvidence), mappings[i:i + 500])
        if ctx is not None and hasattr(ValidateQueryContext, "filter_report"):
            ctx.filter_report = report
        else:
            logger.warning("[filter] filter_report column missing; report not persisted")
        rec.complete_step(filtered_status)
        await db.commit()


async def _mark_failed(query_id: str, message: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
            if rec is not None:
                rec.fail_step(message)
                await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("[filter] could not record failure for %s", query_id)


def _run_blocking(rows: list[Row], plan: dict) -> tuple[list[Decision], dict]:
    return run_filter(rows, plan, get_embedder())      # model load + inference are blocking


async def _handle_validate_filter(query_id: str) -> dict:
    logger.info("[_handle_validate_filter] start query_id=%s", query_id)
    try:
        filtered_status = _require_schema()
        state = await _load(query_id)                  # session closed here
        if _sv(state["status"]) == _sv(filtered_status):
            logger.info("[_handle_validate_filter] %s already filtered; skipping", query_id)
            return {"statusCode": 200, "query_id": query_id, "skipped": True}
        if not state["rows"]:
            raise RuntimeError("No evidence rows found; run the search stage first.")

        decisions, report = await asyncio.to_thread(_run_blocking, state["rows"], state["plan"])
        if report["totals"]["after_filter"] == 0:
            raise RuntimeError("The filter removed all evidence; check thresholds in filter_report.")

        await _save(query_id, filtered_status, decisions, report)
        t = report["totals"]
        logger.info("[_handle_validate_filter] %s: %d collected -> %d after dedupe -> %d selected",
                    query_id, t["collected"], t["after_dedupe"], t["after_filter"])
        return {"statusCode": 200, "query_id": query_id, **t,
                "thin_parameters": report["thin_parameters"]}
    except Exception as exc:
        logger.exception("[_handle_validate_filter] failed query_id=%s: %s", query_id, exc)
        await _mark_failed(query_id, str(exc))
        raise