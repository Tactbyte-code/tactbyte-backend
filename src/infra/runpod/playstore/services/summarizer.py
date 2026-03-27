"""
src/infra/runpod/playstore/services/summarizer.py
──────────────────────────────────────────────────
Generate structured JSON analysis from Play Store reviews.

Multi-call strategy:
  Call 0   → theme discovery
  Call 1   → direct answer / overall verdict
  Call 2   → overview (executive_summary, sentiment, rating breakdown, market signals)
  Call 3…N → one theme per call  (pain points, quotes, system actions)
  Call N+1 → actionable next steps
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import runpod

log = runpod.RunPodLogger()

# ── Constants ────────────────────────────────────────────────────────────────
MAX_REVIEW_CHARS = 400
MAX_REPLY_CHARS  = 200

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM = (
    "You are a senior product analyst specialising in extracting actionable intelligence from app store reviews. "
    "Your sole job is to mine Play Store reviews for concrete, specific insights. "
    "ALWAYS lead with the strongest, most specific finding — name actual features, bugs, use cases, or competitor products users mention. "
    "NEVER open with vague observations, generic sentiment, or filler. "
    "Return ONLY strict, valid JSON. Output MUST start with { and end with }. "
    "Do NOT wrap output in markdown, code fences, or add any explanatory text outside the JSON object."
)

# ── Enum sets for schema repair ───────────────────────────────────────────────
_SENTIMENT_ENUM = {"positive", "negative", "neutral", "mixed"}
_SEVERITY_ENUM  = {"Low", "Medium", "High"}
_CONFIDENCE_ENUM = {"Low", "Medium", "High"}


# ── Schema repair ─────────────────────────────────────────────────────────────
def _repair(result: dict) -> dict:
    """Normalise enum values and coerce bad types in-place."""

    def fix_sentiment(v: Any) -> str:
        if isinstance(v, str):
            l = v.lower()
            if l in _SENTIMENT_ENUM:
                return l
            for s in _SENTIMENT_ENUM:
                if s in l:
                    return s
        return "mixed"

    def fix_severity(v: Any) -> str:
        if isinstance(v, str):
            t = v.strip().title()
            if t in _SEVERITY_ENUM:
                return t
        return "Medium"

    def fix_confidence(v: Any) -> str:
        if isinstance(v, str):
            t = v.strip().title()
            if t in _CONFIDENCE_ENUM:
                return t
        return "Medium"

    def fix_int(v: Any) -> int:
        try:
            return int(v)
        except Exception:
            return 0

    def fix_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return default

    # Top-level fields
    if result.get("overall_sentiment") not in _SENTIMENT_ENUM:
        result["overall_sentiment"] = fix_sentiment(result.get("overall_sentiment", ""))

    if not isinstance(result.get("total_signals"), int):
        result["total_signals"] = fix_int(result.get("total_signals", 0))

    # Meta block
    meta = result.get("meta", {})
    if meta.get("confidence") not in _CONFIDENCE_ENUM:
        meta["confidence"] = fix_confidence(meta.get("confidence", ""))
    result["meta"] = meta

    # Rating breakdown — ensure all keys are str, all values are int
    rb = result.get("rating_breakdown", {})
    result["rating_breakdown"] = {str(k): fix_int(v) for k, v in rb.items()}

    # Themes
    for t in result.get("themes", []):
        if t.get("sentiment") not in _SENTIMENT_ENUM:
            t["sentiment"] = fix_sentiment(t.get("sentiment", ""))
        for f in ("signal_count", "relevance_score"):
            if not isinstance(t.get(f), int):
                t[f] = fix_int(t.get(f, 0))
        # Clamp relevance_score to 0-100
        t["relevance_score"] = max(0, min(100, t["relevance_score"]))

        for pp in t.get("pain_points", []):
            if pp.get("sentiment") not in _SENTIMENT_ENUM:
                pp["sentiment"] = fix_sentiment(pp.get("sentiment", ""))
            if pp.get("severity") not in _SEVERITY_ENUM:
                pp["severity"] = fix_severity(pp.get("severity", ""))

    # Actionable next steps
    for i, step in enumerate(result.get("actionable_next_steps", []), start=1):
        if not isinstance(step.get("priority"), int):
            step["priority"] = fix_int(step.get("priority", i))
        if not isinstance(step.get("quick_win"), bool):
            raw = str(step.get("quick_win", "false")).lower()
            step["quick_win"] = raw in ("true", "1", "yes")

    return result


# ── Context builder ───────────────────────────────────────────────────────────
def _build_context(reviews: list[dict[str, Any]]) -> tuple[str, int]:
    """Serialise reviews into a compact plaintext block for LLM consumption."""
    lines: list[str] = []
    for r in reviews:
        stars   = "★" * (r.get("score") or 0)
        lines.append(
            f"\n=== REVIEW [{r.get('review_id', '')}] {stars} "
            f"thumbs_up={r.get('thumbs_up', 0)} "
            f"date={r.get('review_created', '')} ==="
        )
        lines.append(f"User    : {r.get('username', 'anonymous')}")
        content = (r.get("content") or "")[:MAX_REVIEW_CHARS]
        if content:
            lines.append(f'Content : "{content}"')
        reply = (r.get("reply_content") or "")[:MAX_REPLY_CHARS]
        if reply:
            lines.append(f'DevReply: "{reply}"')
    return "\n".join(lines), len(reviews)


# ── JSON parser ───────────────────────────────────────────────────────────────
def _parse_json(raw: str | None, label: str) -> dict:
    if not raw:
        raise RuntimeError(f"[{label}] LLM returned empty response")
    clean = re.sub(r"```json\s*|```\s*", "", raw).strip()
    clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"[{label}] JSON parse error: {e}\nRaw (first 400):\n{clean[:400]}"
        )


# ── Prompts ───────────────────────────────────────────────────────────────────

def _prompt_discover_themes(app_name: str, context: str) -> str:
    return f"""You are a senior product analyst specialising in app store review analysis.

App: "{app_name}"

Play Store Reviews:
{context}

Identify 3 to 5 DISTINCT, HIGH-VALUE themes that surface directly from the reviews.
Each theme must map to a concrete pattern — a recurring feature request, bug, UX problem, or praised capability.
Avoid generic themes like "User Experience" or "Performance". Name the specific thing users talk about.

Return ONLY this JSON:
{{
  "themes": [
    {{"id": "theme_1", "title": "<specific theme name>", "description": "<one sentence: what pattern this captures>"}},
    {{"id": "theme_2", "title": "<specific theme name>", "description": "<one sentence: what pattern this captures>"}}
  ]
}}"""


def _prompt_direct_answer(app_name: str, context: str) -> str:
    return f"""You are a senior product analyst who has just read hundreds of Play Store reviews for "{app_name}".
Deliver an honest, specific verdict a developer can act on immediately.

Play Store Reviews:
{context}

Instructions:
- Write 3-5 sentences like a trusted analyst giving a frank briefing.
- Sentence 1: The single strongest signal from the reviews — name the specific feature, bug, or pattern most users talk about.
- Sentence 2: The biggest complaint or recurring problem — be specific, no vague language.
- Sentence 3: What users genuinely praise — name it precisely.
- Sentence 4-5 (optional): Edge cases, version-specific issues, or demographic nuance worth flagging.
- Ground every word in the review data. Never use general knowledge or assumptions.

Return ONLY this JSON:
{{
  "direct_answer": "<3-5 analyst-grade sentences grounded entirely in review data>"
}}"""


def _prompt_overview(
    app_name: str,
    context: str,
    now_iso: str,
    total_reviews: int,
    avg_rating: float,
    model_name: str,
    rating_breakdown: dict,
) -> str:
    breakdown_str = json.dumps(rating_breakdown)
    return f"""You are a senior product analyst. Analyse these Play Store reviews for "{app_name}" and produce a structured overview.

Play Store Reviews:
{context}

Return ONLY this JSON — every field is required:
{{
  "analyzed_at": "{now_iso}",
  "executive_summary": "<3-5 sentence neutral digest: what reviewers broadly discuss, major praise, major complaints>",
  "overall_sentiment": "<positive|negative|neutral|mixed>",
  "total_signals": {total_reviews},
  "average_rating": "{avg_rating:.1f}",
  "rating_breakdown": {breakdown_str},
  "market_signals": {{
    "features_praised":    ["<specific feature users love>", "..."],
    "features_requested":  ["<specific feature users want added>", "..."],
    "bugs_reported":       ["<specific bug or crash users mention>", "..."],
    "competitor_mentions": ["<competitor app mentioned by name>", "..."]
  }},
  "meta": {{
    "confidence":     "<High|Medium|Low>",
    "caveats":        "<note sample size, recency bias, or other limitations>",
    "total_reviews":  {total_reviews},
    "average_rating": "{avg_rating:.1f}",
    "model":          "{model_name}"
  }}
}}

Rules:
- market_signals lists must contain specific named items, not vague descriptions.
- If no competitors are mentioned, return an empty list.
- executive_summary must be neutral — do not editorialize."""


def _prompt_theme(
    app_name: str,
    context: str,
    theme_id: str,
    theme_title: str,
    theme_desc: str,
) -> str:
    return f"""You are a senior product analyst. Deeply analyse ONE theme from Play Store reviews for "{app_name}".

Theme: "{theme_title}" — {theme_desc}

Play Store Reviews:
{context}

Focus ONLY on signals relevant to this theme. Ignore unrelated reviews entirely.

Return ONLY this JSON:
{{
  "id": "{theme_id}",
  "title": "{theme_title}",
  "summary": "<2-3 sentences: most specific finding for this theme — name exact features, bugs, or patterns>",
  "sentiment": "<positive|negative|neutral|mixed>",
  "signal_count": <integer: number of reviews relevant to this theme>,
  "relevance_score": <integer 0-100: how central this theme is to overall user experience>,
  "pain_points": [
    {{
      "issue":         "<specific, concrete problem — not vague>",
      "severity":      "<High|Medium|Low>",
      "sentiment":     "<positive|negative|neutral|mixed>",
      "example_quote": "<VERBATIM quote copied exactly from one of the reviews above>",
      "impact":        "<what this costs users — time, money, frustration, churn risk>",
      "user_suggested_solutions": [
        "<exact fix or workaround users mention in the reviews>",
        "<second distinct user suggestion if present>"
      ],
      "system_actions": [
        {{
          "action": "<specific fix, feature change, or product decision>",
          "why":    "<one sentence: why this directly resolves the pain point>",
          "how":    "<1-2 sentences: concrete implementation steps>"
        }}
      ]
    }}
  ]
}}

HARD RULES:
- example_quote values MUST be verbatim from the provided reviews. Never fabricate or paraphrase.
- signal_count must be an integer, not a string.
- severity: exactly one of High, Medium, Low.
- sentiment: exactly one of positive, negative, neutral, mixed.
- If no pain points exist for this theme (it is purely positive), return an empty pain_points list and set sentiment to "positive"."""


def _prompt_actionable_next_steps(
    app_name: str,
    direct_answer: str,
    themes: list[dict],
) -> str:
    # Collect all user-suggested solutions as the evidence base
    evidence: list[dict] = []
    for t in themes:
        for pp in t.get("pain_points", []):
            for sol in pp.get("user_suggested_solutions", []):
                evidence.append({
                    "theme":    t.get("title", ""),
                    "issue":    pp.get("issue", ""),
                    "severity": pp.get("severity", "Medium"),
                    "solution": sol,
                })
    digest = json.dumps(evidence, indent=2)

    return f"""You are a senior product analyst. You have completed a full Play Store review analysis for "{app_name}".

Overall Verdict:
"{direct_answer}"

User-Suggested Solutions (your ONLY source of truth — do not invent steps):
{digest}

Produce a prioritised action list for the product team.
Every step must trace back directly to a user suggestion in the list above.
Rank by: severity × number of affected users × implementation effort (lower effort = higher priority).

Return ONLY this JSON:
{{
  "actionable_next_steps": [
    {{
      "priority":      <integer starting at 1>,
      "step":          "<imperative verb phrase — exactly what to do>",
      "rationale":     "<1-2 sentences: why this matters most to users>",
      "how":           "<2-3 sentences: concrete implementation approach>",
      "effort":        "<realistic estimate: e.g. 1 day, 1 week, 1 sprint>",
      "impact":        "<what concretely improves for users after this is done>",
      "review_source": "<the user suggestion that backs this step>",
      "quick_win":     <true if effort is low and impact is high, otherwise false>
    }}
  ]
}}

Rules:
- Minimum 3 steps, maximum 8.
- quick_win must be a JSON boolean (true or false), not a string.
- Steps must be ordered by priority ascending (1 = do this first)."""


# ── Default filler ────────────────────────────────────────────────────────────
def _fill_defaults(
    result: dict,
    app_name: str,
    model_name: str,
    total_reviews: int,
    avg_rating: float,
    rating_breakdown: dict,
    now_iso: str,
) -> dict:
    result.setdefault("app_name",          app_name)
    result.setdefault("analyzed_at",       now_iso)
    result.setdefault("direct_answer",     "Not enough review data to produce a confident verdict.")
    result.setdefault("executive_summary", "")
    result.setdefault("overall_sentiment", "mixed")
    result.setdefault("total_signals",     total_reviews)
    result.setdefault("average_rating",    f"{avg_rating:.1f}")
    result.setdefault("rating_breakdown",  rating_breakdown)
    result.setdefault("themes",            [])
    result.setdefault("market_signals", {
        "features_praised":    [],
        "features_requested":  [],
        "bugs_reported":       [],
        "competitor_mentions": [],
    })
    result.setdefault("actionable_next_steps", [])
    result.setdefault("meta", {
        "confidence":    "Medium",
        "caveats":       "",
        "total_reviews": total_reviews,
        "average_rating": f"{avg_rating:.1f}",
        "model":         model_name,
    })
    return result


# ── Public entry-point ────────────────────────────────────────────────────────
def run_summarizer(
    reviews: list[dict[str, Any]],
    app_name: str,
    client,
) -> dict[str, Any]:
    """
    Run the full Play Store summarization pipeline.

    Parameters
    ----------
    reviews  : list of review dicts with keys:
                 review_id, score, thumbs_up, review_created,
                 username, content, reply_content
    app_name : human-readable app name (used in all prompts)
    client   : LLM client with .call(system, user) -> str
                 and .model attribute

    Returns
    -------
    Structured analysis dict or {} on fatal failure.
    """
    if not reviews:
        log.warn("[PLAYSTORE][SUMMARIZER] No reviews provided — aborting")
        return {}

    now_iso       = datetime.now(timezone.utc).isoformat()
    model_name    = client.model
    total_reviews = len(reviews)
    context, _    = _build_context(reviews)

    scores         = [r.get("score") for r in reviews if isinstance(r.get("score"), (int, float))]
    avg_rating     = round(sum(scores) / len(scores), 2) if scores else 0.0
    rating_breakdown = {str(i): scores.count(i) for i in range(1, 6)}

    log.info(
        f"[PLAYSTORE][SUMMARIZER] Starting | "
        f"app={app_name!r} reviews={total_reviews} avg_rating={avg_rating}"
    )

    # ── Call 0 — theme discovery ──────────────────────────────────────────────
    log.info("[PLAYSTORE][SUMMARIZER] Call 0 — discovering themes")
    try:
        raw         = client.call(_SYSTEM, _prompt_discover_themes(app_name, context))
        themes_meta = _parse_json(raw, "theme-discovery").get("themes", [])
        log.info(f"[PLAYSTORE][SUMMARIZER] {len(themes_meta)} themes discovered")
    except Exception as e:
        log.error(f"[PLAYSTORE][SUMMARIZER] Theme discovery failed — aborting: {e}")
        return {}

    if not themes_meta:
        log.error("[PLAYSTORE][SUMMARIZER] Zero themes returned — aborting")
        return {}

    # ── Call 1 — direct answer / verdict ─────────────────────────────────────
    log.info("[PLAYSTORE][SUMMARIZER] Call 1 — direct answer")
    direct_answer = "Not enough review data to produce a confident verdict."
    try:
        raw           = client.call(_SYSTEM, _prompt_direct_answer(app_name, context))
        direct_answer = _parse_json(raw, "direct-answer").get("direct_answer", direct_answer)
    except Exception as e:
        log.warn(f"[PLAYSTORE][SUMMARIZER] Direct answer failed — using fallback: {e}")

    # ── Call 2 — overview ─────────────────────────────────────────────────────
    log.info("[PLAYSTORE][SUMMARIZER] Call 2 — overview")
    try:
        raw      = client.call(_SYSTEM, _prompt_overview(
            app_name, context, now_iso, total_reviews,
            avg_rating, model_name, rating_breakdown,
        ))
        overview = _parse_json(raw, "overview")
    except Exception as e:
        log.error(f"[PLAYSTORE][SUMMARIZER] Overview failed — aborting: {e}")
        return {}

    # ── Calls 3…N — one theme per call ───────────────────────────────────────
    themes: list[dict] = []
    for i, tm in enumerate(themes_meta):
        call_num = i + 3
        log.info(f"[PLAYSTORE][SUMMARIZER] Call {call_num} — theme: {tm['title']!r}")
        try:
            raw   = client.call(_SYSTEM, _prompt_theme(
                app_name, context,
                tm["id"], tm["title"], tm.get("description", ""),
            ))
            theme = _parse_json(raw, f"theme-{tm['id']}")
            themes.append(theme)
        except Exception as e:
            log.warn(f"[PLAYSTORE][SUMMARIZER] Theme {tm['title']!r} failed — skipping: {e}")

    # ── Call N+1 — actionable next steps ─────────────────────────────────────
    actionable_next_steps: list[dict] = []
    if themes:
        log.info("[PLAYSTORE][SUMMARIZER] Call N+1 — actionable next steps")
        try:
            raw = client.call(
                _SYSTEM,
                _prompt_actionable_next_steps(app_name, direct_answer, themes),
            )
            ans = _parse_json(raw, "actionable-next-steps")
            actionable_next_steps = ans.get("actionable_next_steps") or []
        except Exception as e:
            log.warn(f"[PLAYSTORE][SUMMARIZER] Actionable next steps failed — skipping: {e}")
    else:
        log.warn("[PLAYSTORE][SUMMARIZER] No themes succeeded — skipping next steps")

    # ── Assemble final result ─────────────────────────────────────────────────
    result: dict[str, Any] = {
        "app_name":            app_name,
        "analyzed_at":         overview.get("analyzed_at",       now_iso),
        "direct_answer":       direct_answer,
        "executive_summary":   overview.get("executive_summary", ""),
        "overall_sentiment":   overview.get("overall_sentiment", "mixed"),
        "total_signals":       overview.get("total_signals",     total_reviews),
        "average_rating":      overview.get("average_rating",    f"{avg_rating:.1f}"),
        "rating_breakdown":    overview.get("rating_breakdown",  rating_breakdown),
        "themes":              themes,
        "market_signals":      overview.get("market_signals", {
            "features_praised":    [],
            "features_requested":  [],
            "bugs_reported":       [],
            "competitor_mentions": [],
        }),
        "actionable_next_steps": actionable_next_steps,
        "meta": overview.get("meta", {
            "confidence":    "Medium",
            "caveats":       "",
            "total_reviews": total_reviews,
            "average_rating": f"{avg_rating:.1f}",
            "model":         model_name,
        }),
    }

    result = _fill_defaults(result, app_name, model_name, total_reviews, avg_rating, rating_breakdown, now_iso)
    result = _repair(result)

    log.info(
        f"[PLAYSTORE][SUMMARIZER] Complete — "
        f"themes={len(result['themes'])} "
        f"steps={len(result['actionable_next_steps'])} "
        f"sentiment={result['overall_sentiment']} "
        f"avg_rating={result['average_rating']}"
    )
    return result