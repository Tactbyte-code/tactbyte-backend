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

Payload budget:
  Azure APIM buffered body limit = 2 MiB (2,097,152 bytes).
  We target 1.5 MiB (1,572,864 bytes) per call to leave headroom for
  prompt text, system instructions, and JSON framing overhead.
  _build_context() enforces this hard ceiling by dropping reviews once
  the encoded byte length would exceed the budget.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

import runpod

log = runpod.RunPodLogger()

# ── Payload budget ────────────────────────────────────────────────────────────
# Azure APIM buffers up to 2 MiB per request body.
# We reserve 512 KiB for prompt text, system instructions, and JSON framing,
# leaving 1.5 MiB for the review context block.
_AZURE_BUFFER_LIMIT_BYTES = 2 * 1024 * 1024          # 2 MiB hard ceiling
_PROMPT_OVERHEAD_BYTES    = 512 * 1024                # 512 KiB reserved for prompt
_CONTEXT_BUDGET_BYTES     = (
    _AZURE_BUFFER_LIMIT_BYTES - _PROMPT_OVERHEAD_BYTES  # 1.5 MiB for reviews
)

# ── Per-review truncation ─────────────────────────────────────────────────────
# Tighter limits reduce per-review byte cost without losing signal.
MAX_REVIEW_CHARS = 220   # was 400 — saves ~45% per review
MAX_REPLY_CHARS  = 100   # was 200

# ── Theme-call review cap ─────────────────────────────────────────────────────
# Per-theme calls receive only keyword-matched reviews, capped here.
_THEME_MAX_REVIEWS = 600

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
_SENTIMENT_ENUM  = {"positive", "negative", "neutral", "mixed"}
_SEVERITY_ENUM   = {"Low", "Medium", "High"}
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
def _build_context(
    reviews: list[dict[str, Any]],
    budget_bytes: int = _CONTEXT_BUDGET_BYTES,
) -> tuple[str, int]:
    """
    Serialise reviews into a compact plaintext block for LLM consumption.

    Reviews are added one at a time. Once adding the next review would push
    the encoded byte length over `budget_bytes`, we stop — ensuring the
    context block never exceeds the Azure APIM 1.5 MiB budget.

    Returns (context_string, reviews_included_count).
    """
    lines: list[str] = []
    total_bytes = 0
    included = 0

    for r in reviews:
        stars   = "★" * (r.get("score") or 0)
        header  = (
            f"\n=== REVIEW [{r.get('review_id', '')}] {stars} "
            f"thumbs_up={r.get('thumbs_up', 0)} "
            f"date={r.get('review_created', '')} ==="
        )
        user_line    = f"User    : {r.get('username', 'anonymous')}"
        content      = (r.get("content") or "")[:MAX_REVIEW_CHARS]
        content_line = f'Content : "{content}"' if content else ""
        reply        = (r.get("reply_content") or "")[:MAX_REPLY_CHARS]
        reply_line   = f'DevReply: "{reply}"' if reply else ""

        block = "\n".join(filter(None, [header, user_line, content_line, reply_line]))
        block_bytes = len(block.encode("utf-8"))

        if total_bytes + block_bytes > budget_bytes:
            log.warn(
                f"[PLAYSTORE][SUMMARIZER] Context budget reached at review {included} "
                f"({total_bytes:,} bytes) — {len(reviews) - included} reviews dropped"
            )
            break

        lines.append(block)
        total_bytes += block_bytes
        included += 1

    log.info(
        f"[PLAYSTORE][SUMMARIZER] Context built: "
        f"{included}/{len(reviews)} reviews, {total_bytes:,} bytes "
        f"(budget {budget_bytes:,} bytes)"
    )
    return "\n".join(lines), included


# ── Theme-relevance filter ────────────────────────────────────────────────────
def _filter_reviews_for_theme(
    reviews: list[dict[str, Any]],
    theme_title: str,
    theme_desc: str,
    max_reviews: int = _THEME_MAX_REVIEWS,
) -> list[dict[str, Any]]:
    """
    Return the reviews most relevant to a given theme using keyword overlap.

    Splits the theme title + description into keyword tokens and scores each
    review by how many keywords appear in its content. Reviews with at least
    one match are returned, sorted by descending match count, capped at
    `max_reviews`. Falls back to the first `max_reviews` reviews if nothing
    matches (rare with well-named themes).
    """
    keywords = set(
        w for w in (theme_title + " " + theme_desc).lower().split()
        if len(w) > 3  # skip stop-word-length tokens
    )

    scored: list[tuple[int, dict]] = []
    for r in reviews:
        text = (
            (r.get("content") or "") + " " + (r.get("reply_content") or "")
        ).lower()
        hits = sum(1 for kw in keywords if kw in text)
        if hits > 0:
            scored.append((hits, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    filtered = [r for _, r in scored[:max_reviews]]

    if not filtered:
        log.warn(
            f"[PLAYSTORE][SUMMARIZER] No keyword matches for theme "
            f"{theme_title!r} — using first {max_reviews} reviews as fallback"
        )
        return reviews[:max_reviews]

    log.info(
        f"[PLAYSTORE][SUMMARIZER] Theme {theme_title!r}: "
        f"{len(filtered)} relevant reviews selected from {len(reviews)}"
    )
    return filtered


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

    Payload strategy
    ----------------
    Each call to client.call() sends at most _CONTEXT_BUDGET_BYTES (1.5 MiB)
    of review text, keeping total request body under Azure APIM's 2 MiB
    buffered payload limit.

    Global calls (theme discovery, direct answer, overview):
      _build_context() enforces the byte budget automatically — reviews are
      added until the next one would exceed 1.5 MiB, then dropped.

    Per-theme calls:
      _filter_reviews_for_theme() selects only keyword-matched reviews
      (capped at _THEME_MAX_REVIEWS = 30), then _build_context() enforces
      the byte budget on that already-small slice. This produces payloads
      well under 200 KB per theme call in practice.
    """
    if not reviews:
        log.warn("[PLAYSTORE][SUMMARIZER] No reviews provided — aborting")
        return {}

    now_iso       = datetime.now(timezone.utc).isoformat()
    model_name    = client.model
    total_reviews = len(reviews)

    scores           = [r.get("score") for r in reviews if isinstance(r.get("score"), (int, float))]
    avg_rating       = round(sum(scores) / len(scores), 2) if scores else 0.0
    rating_breakdown = {str(i): scores.count(i) for i in range(1, 6)}

    log.info(
        f"[PLAYSTORE][SUMMARIZER] Starting | "
        f"app={app_name!r} reviews={total_reviews} avg_rating={avg_rating} "
        f"context_budget={_CONTEXT_BUDGET_BYTES:,}B"
    )

    # Build the shared context for global calls (budget-capped).
    # Theme calls will re-build their own smaller contexts below.
    context, included = _build_context(reviews)

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
    # Each call gets only keyword-relevant reviews, re-budget-capped, so
    # per-theme payloads are typically well under 200 KB.
    themes: list[dict] = []
    for i, tm in enumerate(themes_meta):
        call_num = i + 3
        log.info(f"[PLAYSTORE][SUMMARIZER] Call {call_num} — theme: {tm['title']!r}")
        try:
            theme_reviews = _filter_reviews_for_theme(
                reviews, tm["title"], tm.get("description", "")
            )
            theme_context, _ = _build_context(theme_reviews)
            raw   = client.call(_SYSTEM, _prompt_theme(
                app_name, theme_context,
                tm["id"], tm["title"], tm.get("description", ""),
            ))
            theme = _parse_json(raw, f"theme-{tm['id']}")
            themes.append(theme)
        except Exception as e:
            log.warn(f"[PLAYSTORE][SUMMARIZER] Theme {tm['title']!r} failed — skipping: {e}")

    # ── Call N+1 — actionable next steps ─────────────────────────────────────
    # This call sends only the distilled evidence dict (no raw review text),
    # so its payload is always tiny regardless of corpus size.
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
        f"avg_rating={result['average_rating']} "
        f"reviews_in_context={included}/{total_reviews}"
    )
    return result