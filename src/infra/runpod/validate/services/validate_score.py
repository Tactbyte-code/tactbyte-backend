"""
validate_score.py  (Stages 6 and 7: score each parameter, then aggregate)
=========================================================================
Job:  {"service": "validate", "mode": "score", "query_id": ...}
Status: EXTRACTED -> SCORED        (plain code: no LLM, no embedding model)
Re-running from SCORED / COMPLETED recalculates results (for edited assumptions) and keeps the status.

Reads   validate_query_evidence  WHERE is_selected IS TRUE
          (parameter, source_type, source_url, title, metadata_, extracted_data)
        validate_query_context   (research_plan, filter_report, extract_report)
        validate_query_assumption (editable inputs; defaults are created on the first run)
Writes  validate_parameter_result  one row per parameter
        validate_query_result      one row per query (overall score, breakdown, strengths, risks, data quality)
        validate_query_assumption  missing defaults only (user edits are never overwritten)
        validate_query.status = SCORED

All scores are 0-100, HIGHER = MORE FAVOURABLE FOR LAUNCHING (a high competition score means a
less crowded market; a high cost score means a lighter cost burden). A parameter without enough
evidence gets score = None and status = "insufficient_data"; the overall score is renormalised
over the parameters that were scored.

FORMULAS (summary; see each score_* function)
  pain      100*(.25 volume + .30 intensity + .15 breadth + .15 payment + .15 gap)
  demand    100*(.45 trend + .35 volume + .20 adoption)
  market    100*(.65 size + .35 growth)
  competition 100*(.40 (1-crowding) + .30 (1-incumbent strength) + .30 gap)
  unit_economics 100*weighted mean(ltv_cac .35, payback .25, price_support .20, break_even .20)
  cost      100*mean(1 - first-year cost / SOM revenue, 1 - log-scaled required share)
  regulatory 100*(1 - (.6 requirement load + .4 licence barrier))
  survival_funding 100*mean(funding activity, survival rate)
  macro     100*(.40 growth + .35 inflation + .25 real interest rate)
  overall   sum(score_p * w_p / sum of w over scored parameters), needs >= 60% of the weight scored
"""
from __future__ import annotations

import logging
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from src.core.database import AsyncSessionLocal
from src.app.validate.model import (
    ValidateParameterResult,
    ValidateQuery,
    ValidateQueryAssumption,
    ValidateQueryContext,
    ValidateQueryEvidence,
    ValidateQueryResult,
    ValidateQueryStatus,
)

logger = logging.getLogger(__name__)

SCORING_VERSION = 1
WEIGHTS = {"pain": .20, "market": .15, "competition": .15, "demand": .10, "unit_economics": .10,
           "cost": .10, "regulatory": .10, "survival_funding": .05, "macro": .05}
LABELS = {"pain": "Problem and pain-point severity", "market": "Market size and growth",
          "competition": "Competition and differentiation", "demand": "Demand signals",
          "unit_economics": "Unit economics and pricing", "cost": "Startup cost and runway",
          "regulatory": "Feasibility and regulatory risk", "survival_funding": "Funding climate and survival",
          "macro": "Macro and timing"}
MIN_COVERED_WEIGHT = 0.60
EARLIER_STATUS_NAMES = {"CREATED", "VALIDATED", "SEARCH_COMPLETED", "FILTERED"}
DONE_STATUS_NAMES = {"SCORED", "COMPLETED"}
SOURCE_WEIGHT = {"hn_algolia": 1.0, "appstore_review": 1.0, "stackexchange": 1.0, "youtube": 0.7}  # others 0.5

# (key, label, value, low, high, unit, label_type, affects)
DEFAULT_ASSUMPTIONS: list[tuple] = [
    ("target_segment_fraction", "Share of self-employed workers who are in the target segment", 0.05, 0.03, 0.08, "ratio", "assumed", ["market"]),
    ("digital_adoption", "Share of reachable users who adopt digital tools like this", 0.30, 0.20, 0.40, "ratio", "assumed", ["market"]),
    ("obtainable_share", "Obtainable share of the serviceable market by year 3", 0.01, 0.005, 0.02, "ratio", "assumed", ["market", "unit_economics", "cost"]),
    ("arpu_monthly", "Average revenue per user per month (empty = median competitor price)", None, None, None, "currency", "assumed", ["market", "unit_economics"]),
    ("gross_margin", "Gross margin", 0.80, 0.70, 0.90, "ratio", "assumed", ["unit_economics"]),
    ("monthly_churn", "Monthly customer churn", 0.04, 0.02, 0.08, "ratio", "assumed", ["unit_economics"]),
    ("cac_months_of_arpu", "Customer acquisition cost, in months of ARPU", 6.0, 3.0, 12.0, "months", "assumed", ["unit_economics"]),
    ("units_per_month", "Billable units per customer per month (converts per-use prices)", 10.0, 5.0, 30.0, "count", "assumed", ["unit_economics", "market"]),
    ("headcount_per_role", "Headcount per salaried role", 1.0, 1.0, 2.0, "people", "assumed", ["cost"]),
    ("starting_budget", "Starting budget (optional, used for runway)", None, None, None, "currency", "assumed", ["cost"]),
]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def rating(score: float | None) -> str | None:
    return None if score is None else "strong" if score >= 70 else "moderate" if score >= 50 else "weak"


def band(score: float) -> str:
    return "Strong" if score >= 75 else "Promising" if score >= 55 else "Mixed" if score >= 40 else "Weak"


def r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(float(x), nd)


def pct_of(vals: list[float], q: float) -> float:
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return s[f] + (s[c] - s[f]) * (k - f)


def parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def norm_key(s: str | None, tokens: int = 1) -> str:
    words = re.findall(r"[a-z0-9]{3,}", (s or "").lower())
    return " ".join(words[:tokens])


@dataclass
class Ev:
    id: Any
    parameter: str
    source_type: str
    url: str
    title: str
    meta: dict
    data: dict | None


@dataclass
class PR:
    parameter: str
    score: float | None = None
    confidence: str | None = None
    status: str = "scored"
    components: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)

    @classmethod
    def insufficient(cls, parameter: str, reason: str, **details: Any) -> "PR":
        return cls(parameter, None, None, "insufficient_data", {}, {"reason": reason, **details}, [], [])


class Assumptions:
    def __init__(self, rows: list[dict]):
        self.rows = {x["key"]: x for x in rows}

    def v(self, key: str) -> float | None:
        return (self.rows.get(key) or {}).get("value")

    def lo(self, key: str) -> float | None:
        x = self.rows.get(key) or {}
        return x.get("low") if x.get("low") is not None else x.get("value")

    def hi(self, key: str) -> float | None:
        x = self.rows.get(key) or {}
        return x.get("high") if x.get("high") is not None else x.get("value")

    def user_set(self, key: str) -> bool:
        return (self.rows.get(key) or {}).get("source") == "user"


def merge_assumptions(existing: list[dict]) -> tuple[list[dict], list[dict]]:
    """(all rows incl. defaults, only the default rows that must be inserted)."""
    have = {x["key"]: x for x in existing}
    missing = []
    for key, name, val, lo, hi, unit, lab, affects in DEFAULT_ASSUMPTIONS:
        if key not in have:
            missing.append({"key": key, "name": name, "value": val, "low": lo, "high": hi, "unit": unit,
                            "label": lab, "source": "default", "affects": affects, "editable": True})
    return list(have.values()) + missing, missing


def ids(evs: list[Ev], cap: int = 60) -> list:
    return [e.id for e in evs][:cap]


# --------------------------------------------------------------------------- #
# Parameter 1: pain
# --------------------------------------------------------------------------- #

STOP = set("the and for with that this are was have has but not you your from they their them what when why how "
           "too very can cant its into out all any more most some such than then there here only about over just".split())


def _tf(text: str) -> Counter:
    return Counter(w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP)


def _cos(a: Counter, b: Counter) -> float:
    num = sum(a[k] * b[k] for k in a.keys() & b.keys())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def cluster_summaries(items: list[tuple[str, float, int]], threshold: float = 0.5, top: int = 6) -> list[dict]:
    """items: (summary, intensity, evidence_id). Greedy bag-of-words clustering (no model needed)."""
    clusters: list[dict] = []
    for text, inten, eid in items:
        tf = _tf(text)
        if not tf:
            continue
        best, best_s = None, 0.0
        for c in clusters:
            s = _cos(tf, c["centroid"])
            if s > best_s:
                best, best_s = c, s
        if best is not None and best_s >= threshold:
            best["members"].append((text, inten, eid, tf))
            best["centroid"].update(tf)
        else:
            clusters.append({"centroid": Counter(tf), "members": [(text, inten, eid, tf)]})
    out = []
    for c in clusters:
        rep = max(c["members"], key=lambda m: _cos(m[3], c["centroid"]))
        out.append({"label": rep[0], "post_count": len(c["members"]),
                    "avg_intensity": round(sum(m[1] for m in c["members"]) / len(c["members"]), 2),
                    "evidence_ids": [m[2] for m in c["members"]][:3]})
    return sorted(out, key=lambda x: (x["post_count"], x["avg_intensity"]), reverse=True)[:top]


def pain_item_weight(e: Ev, now: datetime) -> float:
    d = parse_dt(e.meta.get("created_at"))
    recency = max(0.5 ** (max((now - d).days, 0) / 365), 0.2) if d else 0.5          # 12-month half-life
    eng = sum(v for k in ("points", "num_comments") if isinstance(v := e.meta.get(k), (int, float)) and v > 0)
    engagement = 1 + min(math.log1p(eng), 6) / 6                                       # 1.0 .. 2.0
    return recency * engagement * SOURCE_WEIGHT.get(e.source_type, 0.5) * (1.0 if e.data.get("first_hand") else 0.4)


def score_pain(evs: list[Ev], now: datetime, reports: dict) -> PR:
    rel = [e for e in evs if e.parameter == "pain" and e.data and e.data.get("relevant") and e.data.get("segment_match", True)]
    if len(rel) < 5:
        return PR.insufficient("pain", f"only {len(rel)} relevant posts (minimum 5)", relevant=len(rel))
    w = [pain_item_weight(e, now) for e in rel]
    tw = sum(w)
    sources = {e.source_type for e in rel}
    authors = {e.meta.get("author") or e.meta.get("author_hash") or e.id for e in rel}
    pay = {"none": 0.0, "implied": 0.5, "explicit": 1.0}
    gap = {"none_mentioned": 1.0, "inadequate": 0.8, "adequate": 0.2}
    comp = {
        "volume": clip(math.log1p(tw) / math.log1p(40)),
        "intensity": sum(wi * e.data.get("intensity", 0) for wi, e in zip(w, rel)) / (5 * tw),
        "breadth": 0.5 * clip(len(sources) / 4) + 0.5 * clip(len(authors) / 15),
        "payment": sum(wi * pay.get(e.data.get("payment_signal"), 0.0) for wi, e in zip(w, rel)) / tw,
        "gap": sum(wi * gap.get(e.data.get("workaround"), 1.0) for wi, e in zip(w, rel)) / tw,
    }
    score = 100 * (.25 * comp["volume"] + .30 * comp["intensity"] + .15 * comp["breadth"]
                   + .15 * comp["payment"] + .15 * comp["gap"])
    conf = "high" if len(rel) >= 30 and len(sources) >= 3 else "medium" if len(rel) >= 12 and len(sources) >= 2 else "low"
    fr = (reports.get("filter") or {}).get("by_parameter", {}).get("pain", {})
    top = sorted(zip(w, rel), key=lambda t: t[0] * (1 + t[1].data.get("intensity", 0)), reverse=True)[:5]
    return PR("pain", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()},
              {"band": "Severe" if score >= 70 else "Significant" if score >= 50 else "Moderate" if score >= 30 else "Weak",
               "effective_sample": r(tw),
               "counts": {"collected": fr.get("collected"), "after_dedupe": fr.get("after_dedupe"),
                          "after_filter": fr.get("selected"), "relevant": len(rel),
                          "relevant_by_source": dict(Counter(e.source_type for e in rel))},
               "themes": cluster_summaries([(e.data.get("problem_summary") or "", e.data.get("intensity", 0), e.id) for e in rel]),
               "top_evidence": [{"evidence_id": e.id, "source": e.source_type, "url": e.url,
                                 "excerpt": e.data.get("evidence"), "intensity": e.data.get("intensity"),
                                 "workaround": e.data.get("workaround"), "payment_signal": e.data.get("payment_signal")}
                                for _, e in top]},
              ["Online communities over-represent technical and English-speaking users.",
               "Most sources cannot be filtered by country, so evidence may not reflect the target region."],
              ids(rel))


# --------------------------------------------------------------------------- #
# Parameter 3: demand
# --------------------------------------------------------------------------- #


def trend01(change_pct: float) -> float:
    return clip(0.5 + change_pct / 200)


def score_demand(evs: list[Ev]) -> PR:
    trends, used = [], []
    for e in evs:
        if e.parameter != "demand":
            continue
        if e.source_type == "hn_trend" and e.meta.get("change_pct") is not None:
            trends.append((e, clip(e.meta.get("total_mentions", 0) / 50), e.meta["change_pct"]))
        elif e.source_type == "wikipedia_pageviews" and e.meta.get("change_pct_last3_vs_first3") is not None:
            trends.append((e, 1.0 if e.meta.get("match_confidence") == "medium" else 0.5, e.meta["change_pct_last3_vs_first3"]))
    text = [e for e in evs if e.parameter == "demand" and e.data and e.data.get("relevant")]
    tw = sum(t[1] for t in trends)
    if tw <= 0 and len(text) < 5:
        return PR.insufficient("demand", "no usable trend series and fewer than 5 relevant discussions", relevant=len(text))
    comp: dict[str, float] = {}
    weights: dict[str, float] = {}
    if tw > 0:
        comp["trend"] = sum(wt * trend01(p) for _, wt, p in trends) / tw
        weights["trend"] = .45
    comp["volume"] = clip(math.log1p(len(text)) / math.log1p(30))
    weights["volume"] = .35
    comp["adoption"] = (sum(1 for e in text if e.data.get("signal") == "adoption") / len(text)) if text else 0.0
    weights["adoption"] = .20
    score = 100 * sum(weights[k] * comp[k] for k in comp) / sum(weights.values())
    kinds = {e.source_type for e, _, _ in trends}
    conf = "high" if len(kinds) >= 2 and len(text) >= 10 else "medium" if trends or len(text) >= 10 else "low"
    return PR("demand", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()},
              {"search_interest": {"available": False, "reason": "No official free API; unofficial Google Trends access is not used."},
               "relevant_discussions": len(text),
               "signals": [{"name": e.title, "evidence_id": e.id, "source_type": e.source_type, "weight": round(wt, 2),
                            "change_pct": p, "direction": e.meta.get("direction"),
                            "series": e.meta.get("series")} for e, wt, p in trends]},
              ["Trend series from small mention counts are unstable."] if any(e.meta.get("low_volume") for e, _, _ in trends) else [],
              ids([e for e, _, _ in trends] + text))


# --------------------------------------------------------------------------- #
# Shared models: pricing, cost, market (used by several parameters)
# --------------------------------------------------------------------------- #


def build_pricing(evs: list[Ev], a: Assumptions) -> dict:
    units = a.v("units_per_month") or 1.0
    obs = []
    for e in evs:
        d = e.data or {}
        if e.parameter in ("competition", "unit_economics") and d.get("relevant") and (d.get("price_amount") or 0) > 0:
            amt, per = float(d["price_amount"]), d.get("price_period")
            monthly = amt if per == "month" else amt / 12 if per == "year" else amt * units if per == "per_invoice" else None
            if monthly is not None:
                obs.append({"key": norm_key(d.get("name")) or f"ev{e.id}", "monthly": monthly,
                            "currency": (d.get("price_currency") or "").upper(), "model": d.get("pricing_model"), "ev": e})
    if not obs:
        return {"n": 0}
    cur = Counter(o["currency"] for o in obs).most_common(1)[0][0]
    same = [o for o in obs if o["currency"] == cur]
    per_comp: dict[str, dict] = {}
    for o in same:
        if o["key"] not in per_comp or o["monthly"] < per_comp[o["key"]]["monthly"]:
            per_comp[o["key"]] = o                       # lowest paid plan per competitor
    vals = [o["monthly"] for o in per_comp.values()]
    return {"n": len(vals), "currency": cur, "min": min(vals), "p25": pct_of(vals, .25), "median": statistics.median(vals),
            "p75": pct_of(vals, .75), "max": max(vals),
            "models": dict(Counter(o["model"] for o in same if o["model"] and o["model"] != "unknown")),
            "evidence": [o["ev"] for o in per_comp.values()], "dropped_other_currency": len(obs) - len(same)}


def arpu(pricing: dict, a: Assumptions) -> float | None:
    v = a.v("arpu_monthly")
    return v if v else (pricing.get("median") if pricing.get("n") else None)


def _tokens4(s: str | None) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", (s or "").lower()))


def build_cost(evs: list[Ev], plan: dict, a: Assumptions) -> dict:
    cost_plan = plan.get("cost") or {}
    roles, items = cost_plan.get("wage_roles") or [], cost_plan.get("cost_items") or []
    facts = []
    for e in evs:
        d = e.data or {}
        if e.parameter == "cost" and d.get("relevant") and d.get("amount_low") is not None and d.get("period") in ("one_time", "month", "year"):
            div = 12.0 if d["period"] == "year" else 1.0
            lo = float(d["amount_low"]) / div
            hi = float(d["amount_high"] if d.get("amount_high") is not None else d["amount_low"]) / div
            facts.append({"item": d.get("item") or "", "basis": d.get("basis") or "other", "kind": "one_time" if d["period"] == "one_time" else "monthly",
                          "lo": min(lo, hi), "hi": max(lo, hi), "cur": (d.get("currency") or "").upper(), "ev": e})
    if not facts:
        return {"lines": 0}
    cur = Counter(f["cur"] for f in facts).most_common(1)[0][0]
    facts = [f for f in facts if f["cur"] == cur]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for f in facts:
        groups[(f["basis"] == "salary", f["kind"], norm_key(f["item"], 3))].append(f)

    def line(fs: list[dict], mult: float = 1.0) -> dict:
        mids = [(f["lo"] + f["hi"]) / 2 for f in fs]
        return {"item": fs[0]["item"], "kind": fs[0]["kind"], "basis": fs[0]["basis"], "low": min(f["lo"] for f in fs) * mult,
                "base": statistics.median(mids) * mult, "high": max(f["hi"] for f in fs) * mult, "sources": len(fs),
                "evidence_ids": [f["ev"].id for f in fs][:5]}

    head = a.v("headcount_per_role") or 1.0
    lines, salary_groups = [], {k: v for k, v in groups.items() if k[0]}
    chosen: set[tuple] = set()
    for role in roles:                                     # one salary line per planned role
        cand = [(len(_tokens4(role) & _tokens4(v[0]["item"])), len(v), k) for k, v in salary_groups.items()]
        cand = [c for c in cand if c[0] > 0]
        if cand:
            k = max(cand)[2]
            chosen.add(k)
            ln = line(salary_groups[k], head)
            ln["item"] = f"{role} (x{head:g})"
            lines.append(ln)
    if not roles:
        for k, v in sorted(salary_groups.items(), key=lambda kv: -len(kv[1]))[:3]:
            lines.append(line(v, head))
    for k, v in sorted(((k, v) for k, v in groups.items() if not k[0]), key=lambda kv: -len(kv[1]))[:12]:
        lines.append(line(v))
    planned = [p for p in items + roles if p]
    matched = sum(1 for p in planned if any(_tokens4(p) & _tokens4(ln["item"]) for ln in lines))
    tot = lambda kind, k: sum(ln[k] for ln in lines if ln["kind"] == kind)  # noqa: E731
    one = {k: tot("one_time", k) for k in ("low", "base", "high")}
    mon = {k: tot("monthly", k) for k in ("low", "base", "high")}
    first12 = {k: one[k] + 12 * mon[k] for k in one}
    budget = a.v("starting_budget")
    return {"lines": len(lines), "currency": cur, "items": lines, "one_time": one, "monthly_burn": mon, "first_12_months": first12,
            "completeness": round(matched / len(planned), 2) if planned else None,
            "runway_months": round(budget / mon["base"], 1) if budget and mon["base"] > 0 else None,
            "evidence": [f["ev"] for f in facts]}


def _indicator(evs: list[Ev], code: str) -> dict | None:
    c = [e for e in evs if e.parameter == "market" and e.meta.get("indicator_code") == code and e.meta.get("value") is not None]
    return {"ev": c[0], "value": float(c[0].meta["value"]), "year": c[0].meta.get("year"), "history": c[0].meta.get("history") or []} if c else None


def _cagr(history: list[dict]) -> float | None:
    pts = [h["value"] for h in history if isinstance(h.get("value"), (int, float)) and h["value"] > 0]
    return ((pts[-1] / pts[0]) ** (1 / (len(pts) - 1)) - 1) * 100 if len(pts) >= 3 else None


COUNT_UNITS = {"people", "users", "persons", "workers", "businesses", "companies", "freelancers", "professionals"}


def build_market(evs: list[Ev], plan: dict, a: Assumptions, pricing: dict) -> dict:
    labour, selfp, net = (_indicator(evs, c) for c in ("SL.TLF.TOTL.IN", "SL.EMP.SELF.ZS", "IT.NET.USER.ZS"))
    terms = set().union(*[_tokens4(t) for t in (plan.get("market") or {}).get("indicator_search_terms") or []]) or set()
    stated = [e for e in evs if e.parameter == "market" and e.data and e.data.get("relevant") and (e.data.get("value") or 0) > 0
              and str(e.data.get("unit") or "").lower() in COUNT_UNITS and (not terms or terms & _tokens4(e.data.get("metric")))]
    f_lo, f_hi = a.lo("target_segment_fraction"), a.hi("target_segment_fraction")
    derived = (labour["value"] * selfp["value"] / 100 * a.v("target_segment_fraction")) if labour and selfp else None
    if stated:
        vals = [float(e.data["value"]) for e in stated]
        users, u_lo, u_hi, method = statistics.median(vals), min(vals), max(vals), "stated_in_sources"
    elif derived is not None:
        users, method = derived, "derived_from_labour_force"
        u_lo, u_hi = labour["value"] * selfp["value"] / 100 * f_lo, labour["value"] * selfp["value"] / 100 * f_hi
    else:
        return {"users": None}
    net_f = net["value"] / 100 if net else 1.0
    ad, ad_lo, ad_hi = a.v("digital_adoption"), a.lo("digital_adoption"), a.hi("digital_adoption")
    sh, sh_lo, sh_hi = a.v("obtainable_share"), a.lo("obtainable_share"), a.hi("obtainable_share")
    sam = users * net_f * ad
    som = sam * sh
    m = {"users": users, "method": method, "net_factor": net_f, "net_available": net is not None,
         "sam_users": sam, "som_users": som,
         "users_range": (u_lo, u_hi), "sam_range": (u_lo * net_f * ad_lo, u_hi * net_f * ad_hi),
         "som_range": (u_lo * net_f * ad_lo * sh_lo, u_hi * net_f * ad_hi * sh_hi),
         "cross_check": ({"derived_users": derived, "divergence_pct": r((derived - users) / users * 100)} if stated and derived else None),
         "stated_n": len(stated), "labour": labour, "selfp": selfp, "net": net, "stated_ev": stated}
    price = arpu(pricing, a)
    if price:
        lo_p = (pricing["p25"] if pricing.get("n", 0) >= 3 else price * .7) * 12
        hi_p = (pricing["p75"] if pricing.get("n", 0) >= 3 else price * 1.3) * 12
        m.update(price=price * 12, price_range=(lo_p, hi_p), currency=pricing.get("currency"))
    growth = [g for g in (_cagr(labour["history"]) if labour else None, _cagr(net["history"]) if net else None) if g is not None]
    m["cagr_pct"] = sum(growth) if growth else None
    return m


# --------------------------------------------------------------------------- #
# Parameter 2: market, 4: competition, 5: unit economics, 6: cost
# --------------------------------------------------------------------------- #


def score_market(mk: dict, pricing: dict, a: Assumptions) -> PR:
    if mk.get("users") is None:
        return PR.insufficient("market", "no stated customer count and no labour-force / self-employment indicators")
    size = clip(math.log10(max(mk["sam_users"], 1) / 1e4) / math.log10(1e7 / 1e4))      # 10k users -> 0, 10M -> 1
    comp = {"size_adequacy": size}
    score = 100 * size
    if mk.get("cagr_pct") is not None:
        comp["growth"] = clip(0.5 + mk["cagr_pct"] / 20)                                   # 0% -> .5, +10% -> 1
        score = 100 * (.65 * comp["size_adequacy"] + .35 * comp["growth"])
    conf = "high" if mk["stated_n"] and pricing.get("n", 0) >= 3 else "medium" if mk["stated_n"] or pricing.get("n", 0) >= 3 else "low"

    def val(users: float, price: float | None) -> float | None:
        return None if price is None else users * price

    p, pr_lo, pr_hi = mk.get("price"), (mk.get("price_range") or (None, None))[0], (mk.get("price_range") or (None, None))[1]
    cur = mk.get("currency")

    def block(users, rng, price_mult_name, label, formula, inputs):
        v = val(users, p)
        return {"users": r(users, 0), "value": r(v, 0), "currency": cur, "label": label, "formula": formula, "inputs": inputs,
                "range": {"low": r(val(rng[0], pr_lo), 0), "base": r(v, 0), "high": r(val(rng[1], pr_hi), 0)},
                "users_range": {"low": r(rng[0], 0), "high": r(rng[1], 0)}}

    tam = block(mk["users"], mk["users_range"], "tam", "estimated", "addressable_users x annual_price", [
        {"name": "addressable_users", "value": r(mk["users"], 0), "label": "estimated", "method": mk["method"],
         "evidence_ids": [e.id for e in mk["stated_ev"]][:5] or ([mk["labour"]["ev"].id, mk["selfp"]["ev"].id] if mk.get("labour") and mk.get("selfp") else [])},
        {"name": "annual_price_per_user", "value": r(p, 0), "label": "estimated" if pricing.get("n") else "assumed"}])
    sam = block(mk["sam_users"], mk["sam_range"], "sam", "estimated", "TAM users x internet_share x digital_adoption x annual_price", [
        {"name": "internet_share", "value": r(mk["net_factor"], 3), "label": "sourced" if mk["net_available"] else "assumed"},
        {"name": "digital_adoption", "value": a.v("digital_adoption"), "label": "assumed", "assumption_key": "digital_adoption"}])
    som = block(mk["som_users"], mk["som_range"], "som", "assumed", "SAM x obtainable_share", [
        {"name": "obtainable_share", "value": a.v("obtainable_share"), "label": "assumed", "assumption_key": "obtainable_share"}])
    caveats = ["Market size is a range built from assumptions and low-confidence inputs."]
    if p is None:
        caveats.append("No pricing evidence: market values are not computed (set the arpu_monthly assumption).")
    if not mk["net_available"]:
        caveats.append("Internet-user share missing: SAM ignores it.")
    ev = (mk["stated_ev"] + [x["ev"] for x in (mk.get("labour"), mk.get("selfp"), mk.get("net")) if x])
    return PR("market", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()},
              {"tam": tam, "sam": sam, "som": {**som, "horizon_years": 3}, "cross_check": mk["cross_check"],
               "growth": ({"cagr_pct": r(mk["cagr_pct"]), "label": "estimated", "confidence": "low",
                           "basis": "Growth of labour force plus growth of internet-user share (proxy)"} if mk.get("cagr_pct") is not None else None)},
              caveats, ids(ev))


def build_competitors(evs: list[Ev]) -> dict:
    groups: dict[str, list[Ev]] = defaultdict(list)
    for e in evs:
        d = e.data or {}
        if e.parameter in ("competition", "unit_economics") and d.get("relevant") and d.get("name"):
            groups[norm_key(d["name"])].append(e)
    comps = []
    for key, es in groups.items():
        if not key:
            continue
        ds = [e.data for e in es]
        priced = [(d["price_amount"], d) for d in ds if (d.get("price_amount") or 0) > 0]
        low = min(priced, key=lambda t: t[0])[1] if priced else None
        wk = Counter(w for d in ds for w in d.get("weaknesses") or [])
        st = Counter(w for d in ds for w in d.get("strengths") or [])
        models = Counter(d.get("pricing_model") for d in ds if d.get("pricing_model") not in (None, "unknown"))
        comps.append({"name": Counter(d["name"] for d in ds).most_common(1)[0][0],
                      "offering": next((d["offering"] for d in ds if d.get("offering")), ""),
                      "pricing_model": models.most_common(1)[0][0] if models else "unknown",
                      "price_from": ({"amount": low["price_amount"], "currency": low.get("price_currency"), "period": low.get("price_period")} if low else None),
                      "target_segment": next((d["target_segment"] for d in ds if d.get("target_segment")), None),
                      "strengths": [w for w, _ in st.most_common(3)], "weaknesses": [w for w, _ in wk.most_common(3)],
                      "evidence_url": es[0].url, "evidence_ids": [e.id for e in es][:5],
                      "confidence": "medium" if len(es) >= 2 else "low", "funding": None, "revenue": None})
    listings = [e for e in evs if e.source_type == "appstore_listing"]
    rc = [e.meta.get("rating_count") for e in listings if isinstance(e.meta.get("rating_count"), (int, float))]
    return {"competitors": comps, "max_rating_count": max(rc) if rc else None, "listings": listings}


def score_competition(cb: dict, pain: PR) -> PR:
    comps = cb["competitors"]
    n = len(comps)
    if n == 0:
        return PR.insufficient("competition", "no competitor could be identified from the evidence (blue ocean or weak retrieval)")
    crowd = clip(n / 10)
    strength = clip(math.log10(1 + cb["max_rating_count"]) / 6) if cb["max_rating_count"] else 0.5      # 1M ratings -> 1
    weak_share = sum(1 for c in comps if c["weaknesses"]) / n
    gaps = [weak_share] + ([pain.components["gap"]] if pain.status == "scored" else [])
    gap = sum(gaps) / len(gaps)
    comp = {"crowding": crowd, "incumbent_strength": strength, "gap": gap}
    score = 100 * (.40 * (1 - crowd) + .30 * (1 - strength) + .30 * gap)
    conf = "high" if n >= 5 and cb["listings"] else "medium" if n >= 3 else "low"
    wk = Counter(w for c in comps for w in c["weaknesses"])
    return PR("competition", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()},
              {"counts": {"direct": n}, "saturation": "high" if n >= 7 else "moderate" if n >= 4 else "low",
               "incumbent_strength": ("strong" if strength >= .66 else "moderate" if strength >= .33 else "weak") if cb["max_rating_count"] else "unknown",
               "direct_competitors": comps, "gap_candidates": [w for w, _ in wk.most_common(5)],
               "physical_density": None},
              ["Competitor revenue, traffic and funding are not available from free sources."]
              + ([] if cb["max_rating_count"] else ["No app-store listing found: incumbent strength is a neutral default."]),
              [i for c in comps for i in c["evidence_ids"]][:60])


def unit_economics_model(pricing: dict, cost: dict, mk: dict, a: Assumptions) -> dict | None:
    p = arpu(pricing, a)
    if not p:
        return None
    gm, churn, cac_m = a.v("gross_margin"), a.v("monthly_churn"), a.v("cac_months_of_arpu")
    cac = p * cac_m
    contrib = p * gm
    m = {"arpu": p, "gross_margin": gm, "churn": churn, "cac": cac, "ltv": contrib / churn, "ltv_cac": (contrib / churn) / cac,
         "payback_months": cac / contrib, "currency": pricing.get("currency")}
    burn = (cost.get("monthly_burn") or {}).get("base")
    same_cur = burn and cost.get("currency") == pricing.get("currency")
    m["break_even_users"] = burn / contrib if same_cur else None
    m["currency_mismatch"] = bool(burn) and not same_cur
    return m


def score_unit_economics(ue: dict | None, pricing: dict, mk: dict, a: Assumptions) -> PR:
    if ue is None:
        return PR.insufficient("unit_economics", "no price observations and no arpu_monthly assumption")
    comp = {"ltv_cac": clip((ue["ltv_cac"] - 1) / 4), "payback": clip((24 - ue["payback_months"]) / 18),
            "price_support": clip(pricing.get("n", 0) / 6)}
    w = {"ltv_cac": .35, "payback": .25, "price_support": .20}
    if ue["break_even_users"] and mk.get("som_users"):
        comp["break_even"] = clip((1 - ue["break_even_users"] / mk["som_users"]) / 0.8)
        w["break_even"] = .20
    score = 100 * sum(w[k] * comp[k] for k in comp) / sum(w.values())
    user_inputs = a.user_set("monthly_churn") and a.user_set("cac_months_of_arpu")
    conf = "medium" if user_inputs and pricing.get("n", 0) >= 3 else "low"
    return PR("unit_economics", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()},
              {"pricing_benchmarks": ({"sample_size": pricing["n"], "models": pricing["models"], "currency": pricing["currency"],
                                       "monthly_price": {k: r(pricing[k], 2) for k in ("min", "p25", "median", "p75", "max")},
                                       "label": "sourced"} if pricing.get("n") else None),
               "model": {"arpu_monthly": r(ue["arpu"], 2), "gross_margin": ue["gross_margin"], "monthly_churn": ue["churn"],
                         "cac": r(ue["cac"], 2), "currency": ue["currency"], "label": "assumed",
                         "assumption_keys": ["arpu_monthly", "gross_margin", "monthly_churn", "cac_months_of_arpu"]},
               "derived": {"ltv": r(ue["ltv"], 2), "ltv_cac_ratio": r(ue["ltv_cac"], 2), "cac_payback_months": r(ue["payback_months"], 1),
                           "break_even_paying_users": r(ue["break_even_users"], 0), "currency": ue["currency"]}},
              ["CAC, churn and margin are assumptions; replace them with pilot data."]
              + (["Cost and price currencies differ: break-even was not computed."] if ue["currency_mismatch"] else []),
              ids(pricing.get("evidence", [])))


def score_cost(cost: dict, mk: dict, ue: dict | None) -> PR:
    if not cost.get("lines"):
        return PR.insufficient("cost", "no usable cost figures were extracted")
    comp: dict[str, float] = {}
    som_rev = None
    if mk.get("price") and mk.get("som_users") and mk.get("currency") == cost["currency"]:
        som_rev = mk["som_users"] * mk["price"]
        comp["cost_vs_revenue"] = clip(1 - cost["first_12_months"]["base"] / som_rev)
    if ue and ue.get("break_even_users") and mk.get("sam_users"):
        share = ue["break_even_users"] / mk["sam_users"]
        comp["required_share"] = clip(1 - math.log10(max(share, 1e-9) / 0.001) / math.log10(0.02 / 0.001))   # 0.1% -> 1, 2% -> 0
    details = {"currency": cost["currency"], "items": cost["items"], "one_time": cost["one_time"], "monthly_burn": cost["monthly_burn"],
               "first_12_months": cost["first_12_months"], "completeness": cost["completeness"],
               "runway_months": cost["runway_months"], "som_revenue_base": r(som_rev, 0)}
    caveats = ["Figures come from scraped web pages; verify before relying on them."]
    if not comp:
        return PR("cost", None, None, "insufficient_data", {}, {**details, "reason": "cost lines found, but no market/price data to judge the burden"},
                  caveats, ids(cost["evidence"]))
    score = 100 * sum(comp.values()) / len(comp)
    c, n = cost["completeness"] or 0, cost["lines"]
    conf = "high" if c >= .8 and n >= 6 else "medium" if c >= .5 and n >= 3 else "low"
    return PR("cost", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()}, details, caveats, ids(cost["evidence"]))


# --------------------------------------------------------------------------- #
# Parameters 7, 8, 9: regulatory, survival/funding, macro
# --------------------------------------------------------------------------- #

BARRIER = re.compile(r"licen[cs]e|authori[sz]ation|prior approval|permit|certification|registration with", re.I)


def score_regulatory(evs: list[Ev]) -> PR:
    facts = [e for e in evs if e.parameter in ("regulatory", "cost") and e.data and e.data.get("relevant") and e.data.get("requirement")]
    uniq: dict[str, Ev] = {}
    for e in facts:
        uniq.setdefault(norm_key(e.data["requirement"], 8), e)
    if len(uniq) < 2:
        return PR.insufficient("regulatory", f"only {len(uniq)} requirement(s) found (minimum 2)")
    reqs = list(uniq.values())
    barrier = sum(1 for e in reqs if not e.data.get("conditional") and BARRIER.search(e.data["requirement"]))
    comp = {"requirement_load": clip(len(reqs) / 10), "licence_barrier": clip(barrier / 3)}
    score = 100 * (1 - (.6 * comp["requirement_load"] + .4 * comp["licence_barrier"]))
    auth = sum(1 for e in reqs if e.data.get("authority"))
    conf = "high" if len(reqs) >= 10 and auth / len(reqs) >= .5 else "medium" if len(reqs) >= 6 and len({e.url for e in reqs}) >= 3 else "low"
    return PR("regulatory", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()},
              {"complexity": "high" if score < 40 else "moderate" if score < 70 else "low", "legal_review_recommended": True,
               "requirements": [{"requirement": e.data["requirement"], "authority": e.data.get("authority"), "applies_to": e.data.get("applies_to"),
                                 "conditional": e.data.get("conditional"), "note": e.data.get("note"), "evidence_id": e.id, "url": e.url}
                                for e in reqs[:15]]},
              ["Not legal advice: have a professional review the requirements."], ids(reqs))


def score_survival_funding(evs: list[Ev], now: datetime) -> PR:
    facts = [e for e in evs if e.parameter == "survival_funding" and e.data and e.data.get("relevant")]
    fund = [e for e in facts if e.data.get("kind") in ("funding_round", "grant")]
    surv = [e for e in facts if e.data.get("kind") == "survival_stat" and e.data.get("amount") is not None and 0 <= e.data["amount"] <= 100]
    comp: dict[str, float] = {}
    if fund:
        weight = sum(1.0 if (e.data.get("year") or 0) >= now.year - 3 else 0.5 for e in fund)
        comp["funding_activity"] = clip(weight / 8)
    if surv:
        comp["survival_rate"] = clip(statistics.mean(e.data["amount"] for e in surv) / 100)
    if not comp:
        return PR.insufficient("survival_funding", "no usable funding or survival figures from free sources")
    score = 100 * sum(comp.values()) / len(comp)
    conf = "medium" if len(facts) >= 8 else "low"
    return PR("survival_funding", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()},
              {"reference_benchmarks": [{"region": e.data.get("region"), "value_pct": e.data["amount"], "year": e.data.get("year"),
                                         "evidence_id": e.id, "url": e.url, "label": "sourced"} for e in surv],
               "funding_activity": {"rounds_or_grants": len(fund)} if fund else None},
              ["Free sources rarely cover seed funding or sector survival for most countries."], ids(facts))


def score_macro(evs: list[Ev], now: datetime) -> PR:
    ind = {}
    for e in evs:
        if e.parameter == "macro" and e.meta.get("indicator_code") and e.meta.get("value") is not None:
            ind[e.meta["indicator_code"]] = e
    spec = {"NY.GDP.MKTP.KD.ZG": ("growth", .40, lambda v: clip(v / 8)),                    # 8%+ growth -> 1
            "FP.CPI.TOTL.ZG": ("inflation", .35, lambda v: clip((12 - v) / 8)),            # <=4% -> 1, >=12% -> 0
            "FR.INR.RINR": ("real_rate", .25, lambda v: clip(1 - v / 8))}                  # <=0 -> 1, >=8 -> 0
    comp, w = {}, {}
    for code, (name, wt, fn) in spec.items():
        if code in ind:
            comp[name], w[name] = fn(float(ind[code].meta["value"])), wt
    if not comp:
        return PR.insufficient("macro", "no macro indicators were retrieved")
    score = 100 * sum(w[k] * comp[k] for k in comp) / sum(w.values())
    fresh = all(int(str(e.meta.get("year") or 0)[:4] or 0) >= now.year - 3 for e in ind.values())
    conf = "high" if len(comp) == 3 and fresh else "medium" if len(comp) >= 2 else "low"
    return PR("macro", r(score), conf, "scored", {k: round(v, 3) for k, v in comp.items()},
              {"outlook": "supportive" if score >= 65 else "neutral" if score >= 45 else "challenging",
               "indicators": [{"name": e.meta.get("indicator_name"), "indicator_code": c, "value": e.meta["value"], "year": e.meta.get("year"),
                               "label": "sourced", "evidence_id": e.id} for c, e in ind.items()]},
              [], ids(list(ind.values())))


# --------------------------------------------------------------------------- #
# Stage 7: aggregate
# --------------------------------------------------------------------------- #

STRENGTH = {"pain": "Recurring, first-hand complaints show a real problem", "market": "The serviceable market looks large enough",
            "competition": "The market is not overly crowded and competitors show gaps", "demand": "Interest in the topic is rising",
            "unit_economics": "Pricing evidence supports a viable revenue model", "cost": "Estimated launch cost is light relative to potential revenue",
            "regulatory": "Few regulatory hurdles were found", "survival_funding": "Funding activity or survival rates look supportive",
            "macro": "Macro conditions are supportive"}
RISK = {"pain": "The problem may not be severe or frequent enough", "market": "The serviceable market may be small",
        "competition": "Crowded market with strong incumbents", "demand": "Interest in the topic is flat or falling",
        "unit_economics": "Unit economics look weak under current assumptions", "cost": "Launch cost is heavy relative to potential revenue",
        "regulatory": "Significant regulatory or licensing burden", "survival_funding": "Funding or survival data look unfavourable",
        "macro": "Macro conditions are challenging"}


def aggregate(results: dict[str, PR], assumptions: list[dict], reports: dict, evs: list[Ev]) -> dict:
    scored = {p: x for p, x in results.items() if x.score is not None}
    covered = sum(WEIGHTS[p] for p in scored)
    breakdown = []
    overall = None
    for p in WEIGHTS:
        x = results.get(p)
        eff = WEIGHTS[p] / covered if x and x.score is not None and covered else 0.0
        breakdown.append({"parameter": p, "label": LABELS[p], "weight": WEIGHTS[p], "effective_weight": round(eff, 4),
                          "score": x.score if x else None, "rating": rating(x.score) if x else None,
                          "confidence": x.confidence if x else None, "status": x.status if x else "insufficient_data",
                          "contribution": r(x.score * eff) if x and x.score is not None else None})
    if covered >= MIN_COVERED_WEIGHT:
        # overall = round(sum(b["contribution"] or 0 for b in breakdown), 1)
        overall = round(sum(scored[p].score * WEIGHTS[p] for p in scored) / covered, 1)
    conf_val = {"high": 1.0, "medium": 0.6, "low": 0.3}
    idx = sum(b["effective_weight"] * conf_val.get(b["confidence"], 0.3) for b in breakdown)
    overall_conf = ("high" if idx >= .75 and covered >= .85 else "medium" if idx >= .45 and covered >= .60 else "low")

    strengths, risks = [], []
    for p, x in sorted(scored.items(), key=lambda kv: -kv[1].score):
        if x.score >= 70 and x.confidence in ("medium", "high"):
            strengths.append({"parameter": p, "text": STRENGTH[p]})
    for p, x in sorted(scored.items(), key=lambda kv: kv[1].score):
        if x.score < 50:
            risks.append({"parameter": p, "text": RISK[p]})
    pn = results.get("pain")
    if pn and pn.score is not None and pn.components.get("payment", 1) < .4:
        risks.append({"parameter": "pain", "text": "Willingness to pay is only weakly evidenced"})
    ue = results.get("unit_economics")
    if ue and ue.score is not None and ue.confidence == "low":
        risks.append({"parameter": "unit_economics", "text": "CAC and churn are assumptions, not measured data"})
    missing = [LABELS[p] for p in WEIGHTS if p not in scored]
    if missing:
        risks.append({"parameter": None, "text": "No usable data for: " + ", ".join(missing)})

    years = [int(str(e.meta["year"])[:4]) for e in evs if e.meta.get("year") and str(e.meta["year"])[:4].isdigit()]
    fr, xr = reports.get("filter") or {}, reports.get("extract") or {}
    labels = Counter(x.get("label") for x in assumptions)
    return {
        "viability_score": overall, "band": band(overall) if overall is not None else "Insufficient evidence",
        "confidence": overall_conf if overall is not None else "low", "covered_weight": round(covered, 2),
        "breakdown": breakdown, "strengths": strengths[:4], "risks": risks[:6],
        "data_quality": {
            "parameters_scored": len(scored), "parameters_insufficient": [p for p in WEIGHTS if p not in scored],
            "evidence_items_total": (fr.get("totals") or {}).get("collected"),
            "evidence_items_selected": (fr.get("totals") or {}).get("after_filter"),
            "evidence_items_relevant": sum(v.get("relevant", 0) for v in (xr.get("by_parameter") or {}).values()) or None,
            "thin_parameters": fr.get("thin_parameters", []), "oldest_data_year": min(years) if years else None,
            "assumption_labels": dict(labels),
            "limitations": ["Free sources lack competitor revenue, traffic, funding, CAC and churn.",
                            "Community sources skew technical and English-speaking.",
                            "Scores are directional estimates, not probabilities of success."]},
    }


def run_scoring(evs: list[Ev], plan: dict, assumption_rows: list[dict], reports: dict | None = None,
                now: datetime | None = None) -> tuple[dict[str, PR], dict, list[dict], list[dict]]:
    reports = reports or {}
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    all_rows, missing = merge_assumptions(assumption_rows)
    a = Assumptions(all_rows)
    pain = score_pain(evs, now, reports)
    pricing = build_pricing(evs, a)
    cost = build_cost(evs, plan, a)
    mk = build_market(evs, plan, a, pricing)
    ue = unit_economics_model(pricing, cost, mk, a)
    results = {
        "pain": pain, "demand": score_demand(evs), "market": score_market(mk, pricing, a),
        "competition": score_competition(build_competitors(evs), pain),
        "unit_economics": score_unit_economics(ue, pricing, mk, a), "cost": score_cost(cost, mk, ue),
        "regulatory": score_regulatory(evs), "survival_funding": score_survival_funding(evs, now), "macro": score_macro(evs, now)}
    return results, aggregate(results, all_rows, reports, evs), all_rows, missing


# --------------------------------------------------------------------------- #
# Database phases + handler
# --------------------------------------------------------------------------- #


def _sv(status: Any) -> Any:
    return getattr(status, "value", status)


def _require_schema() -> Any:
    for name in ("ValidateParameterResult", "ValidateQueryAssumption", "ValidateQueryResult"):
        if globals().get(name) is None:
            raise RuntimeError(f"Model {name} is missing; add the Stage 6/7 tables first (see validate_score_models.py).")
    scored = getattr(ValidateQueryStatus, "SCORED", None)
    if scored is None:
        raise RuntimeError("ValidateQueryStatus.SCORED is missing; add it (ALTER TYPE ... ADD VALUE if native enum).")
    return scored


async def _load(query_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
        ctx = (await db.execute(select(ValidateQueryContext).where(ValidateQueryContext.query_id == query_id))).scalars().first()
        if not rec or not ctx:
            raise ValueError(f"Missing records for query {query_id} to proceed with Stage 6/7.")
        rows = (await db.execute(select(ValidateQueryEvidence).where(
            ValidateQueryEvidence.query_id == query_id, ValidateQueryEvidence.is_selected.is_(True)))).scalars().all()
        ass = (await db.execute(select(ValidateQueryAssumption).where(ValidateQueryAssumption.query_id == query_id))).scalars().all()
        return {
            "plan": dict(ctx.research_plan or {}), "status": getattr(rec, "status", None),
            "reports": {"filter": getattr(ctx, "filter_report", None), "extract": getattr(ctx, "extract_report", None)},
            "evs": [Ev(str(e.id), e.parameter, e.source_type, e.source_url, e.title or "", dict(e.metadata_ or {}), dict(e.extracted_data) if e.extracted_data else None) for e in rows],
            "assumptions": [{"key": x.key, "name": x.name, "value": x.value, "low": x.low, "high": x.high, "unit": x.unit,
                             "label": x.label, "source": x.source, "affects": x.affects, "editable": x.editable} for x in ass]}


async def _save(query_id: str, results: dict[str, PR], overall: dict, snapshot: list[dict], missing: list[dict],
                scored_status: Any, advance: bool) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
        if rec is None:
            raise ValueError(f"ValidateQuery {query_id} disappeared before the save step.")
        await db.execute(delete(ValidateParameterResult).where(ValidateParameterResult.query_id == query_id))
        await db.execute(delete(ValidateQueryResult).where(ValidateQueryResult.query_id == query_id))
        for p, x in results.items():
            db.add(ValidateParameterResult(
                query_id=query_id, parameter=p, status=x.status, score=x.score, rating=rating(x.score), confidence=x.confidence,
                components=x.components, details=x.details, caveats=x.caveats, evidence_ids=x.evidence_ids,
                scoring_version=SCORING_VERSION, computed_at=now))
        db.add(ValidateQueryResult(
            query_id=query_id, viability_score=overall["viability_score"], band=overall["band"], confidence=overall["confidence"],
            breakdown=overall["breakdown"], strengths=overall["strengths"], risks=overall["risks"],
            data_quality=overall["data_quality"], assumptions=snapshot, scoring_version=SCORING_VERSION, computed_at=now))
        for m in missing:
            db.add(ValidateQueryAssumption(query_id=query_id, **m))
        if advance:
            rec.complete_step(scored_status)
        await db.commit()


async def _mark_failed(query_id: str, message: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            rec = (await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))).scalars().first()
            if rec is not None:
                rec.fail_step(message)
                await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("[score] could not record failure for %s", query_id)


async def _handle_validate_score(query_id: str) -> dict:
    logger.info("[_handle_validate_score] start query_id=%s", query_id)
    try:
        scored_status = _require_schema()
        st = await _load(query_id)                                  # session closed here
        name = str(_sv(st["status"]))
        if name in EARLIER_STATUS_NAMES:
            raise RuntimeError(f"Status is {name}: run the extraction stage before scoring.")
        results, overall, snapshot, missing = run_scoring(st["evs"], st["plan"], st["assumptions"], st["reports"])
        advance = name not in DONE_STATUS_NAMES                     # recalculation keeps SCORED / COMPLETED
        await _save(query_id, results, overall, snapshot, missing, scored_status, advance)
        logger.info("[_handle_validate_score] %s: overall=%s (%s), %d/9 parameters scored",
                    query_id, overall["viability_score"], overall["band"], overall["data_quality"]["parameters_scored"])
        return {"statusCode": 200, "query_id": query_id, "viability_score": overall["viability_score"], "band": overall["band"],
                "confidence": overall["confidence"], "parameters_scored": overall["data_quality"]["parameters_scored"],
                "parameters_insufficient": overall["data_quality"]["parameters_insufficient"], "recalculated": not advance}
    except Exception as exc:
        logger.exception("[_handle_validate_score] failed query_id=%s: %s", query_id, exc)
        await _mark_failed(query_id, str(exc))
        raise