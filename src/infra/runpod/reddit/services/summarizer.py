#!/usr/bin/env python3
"""
module/summarizer.py
─────────────────────────────────────────────────────────────────────────────
Generate a structured JSON summary from gate4_passed posts using any LLM
via the shared LLMClient (Claude, GPT, Gemini, Qwen, HF, mock).
CALL STRATEGY (prevents truncation, guarantees schema compliance):
  Call 0    → theme discovery       : identify N theme titles + 1-line descriptions
  Call 1    → direct answer         : warm, consultant-grade answer from Reddit data only
  Call 2    → overview              : executive_summary, overall_sentiment,
                                       total_signals, market_signals, meta
  Call 3…N  → one theme per call   : full theme object with pain_points, quotes,
                                       sources, reddit_user_actions, system_actions
  Call N+1  → actionable_next_steps : ordered how-to steps to accomplish direct answer,
                                       backed by Reddit user suggestions only
  Final     → assemble + repair + validate

RELIABILITY NOTE:
  client.call() can legitimately hand back an empty string with no exception
  raised (provider-side content filter, truncated/cold-start response, an
  input too long for the model's context window, a transient network blip,
  etc). Every LLM call in this module goes through `_call_part()` (same
  pattern as query_generator.py's part-caller): it retries on call errors,
  empty responses, and JSON parse failures, and returns None once retries
  are exhausted instead of raising. Callers decide the fallback — so a
  single call that keeps failing (e.g. theme discovery on an oversized
  prompt) degrades that one section instead of aborting the whole run.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from typing import Any
import runpod

log = runpod.RunPodLogger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_POST_BODY_CHARS    = 600
MAX_COMMENT_BODY_CHARS = 350
MAX_COMMENTS_PER_POST  = 10

# Hard cap on the compact Reddit context we ever send to the LLM. Oversized,
# uncurated context is a common trigger for provider-side truncation or
# silent content-filter blocks (which surface here as an empty response).
MAX_CONTEXT_CHARS = 60_000

# Retry policy for every LLM call in this module (mirrors query_generator.py).
LLM_MAX_RETRIES = 3   # total attempts per call before giving up on that part

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM = (
    "You are a warm, senior product researcher and consultant with deep expertise in extracting actionable intelligence from social media data. "
    "Your sole job is to mine Reddit posts and comments for concrete, specific insights that directly answer the user's query. "
    "ALWAYS lead with the strongest, most specific finding — name actual tools, products, services, workarounds, or methods users mention. "
    "NEVER open with vague observations, generic sentiment, or filler. "
    "Return ONLY strict, valid JSON. Output MUST start with { and end with }. "
    "EXCLUDE any post, comment, or signal that is not directly relevant to the query — treat off-topic data as if it does not exist. "
    "Do NOT wrap output in markdown, code fences, or add any explanatory text outside the JSON object."
)

# ---------------------------------------------------------------------------
# Schema repair
# ---------------------------------------------------------------------------
_SENTIMENT_ENUM = {"positive", "negative", "neutral", "mixed"}
_SEVERITY_ENUM  = {"Low", "Medium", "High"}
_KIND_ENUM      = {"post", "comment"}

def _repair(result: dict) -> dict:
    """Snap common LLM deviations to valid schema values without re-calling the API."""
    def fix_sentiment(v):
        if isinstance(v, str):
            l = v.lower()
            if l in _SENTIMENT_ENUM: return l
            for s in _SENTIMENT_ENUM:
                if s in l: return s
        return "mixed"

    def fix_severity(v):
        if isinstance(v, str):
            t = v.strip().title()
            if t in _SEVERITY_ENUM: return t
        return "Medium"

    def fix_int(v):
        try: return int(v)
        except: return 0

    if result.get("overall_sentiment") not in _SENTIMENT_ENUM:
        result["overall_sentiment"] = fix_sentiment(result.get("overall_sentiment", ""))

    if not isinstance(result.get("total_signals"), int):
        result["total_signals"] = fix_int(result.get("total_signals", 0))

    for t in result.get("themes", []):
        if t.get("sentiment") not in _SENTIMENT_ENUM:
            t["sentiment"] = fix_sentiment(t.get("sentiment", ""))
        for f in ("signal_count", "relevance_score"):
            if not isinstance(t.get(f), int):
                t[f] = fix_int(t.get(f, 0))
        for pp in t.get("pain_points", []):
            if pp.get("sentiment") not in _SENTIMENT_ENUM:
                pp["sentiment"] = fix_sentiment(pp.get("sentiment", ""))
            if pp.get("severity") not in _SEVERITY_ENUM:
                pp["severity"] = fix_severity(pp.get("severity", ""))
        for q in t.get("quotes", []):
            if not isinstance(q.get("score"), int):
                q["score"] = fix_int(q.get("score", 0))
        for s in t.get("sources", []):
            if s.get("kind") not in _KIND_ENUM:
                s["kind"] = "comment" if "comment" in str(s.get("kind", "")).lower() else "post"
            if not isinstance(s.get("score"), int):
                s["score"] = fix_int(s.get("score", 0))

    return result

# ---------------------------------------------------------------------------
# Context builder — posts → compact text for LLM prompts
# ---------------------------------------------------------------------------
def _build_context(posts: list[dict[str, Any]]) -> tuple[str, int]:
    """Builds compact text context from gate4_passed posts. Returns (context_str, total_comments)."""
    lines          = []
    total_comments = 0

    for post in posts:
        lines.append(
            f"\n=== POST [{post.get('reddit_url', post.get('url', ''))}] "
            f"r/{post.get('reddit_subreddit', '')} ==="
        )
        lines.append(f"Title : {post.get('reddit_title', '')}")
        lines.append(
            f"Score : {post.get('reddit_score', 0)} | "
            f"Date  : {post.get('reddit_created_utc', '')} | "
            f"BGE   : {post.get('bge_score', '')}"
        )
        body = post.get("reddit_selftext", "") or ""
        if body and body not in ("[deleted]", "[removed]", ""):
            lines.append(f"Body  : {body[:MAX_POST_BODY_CHARS]}")

        comments = post.get("reddit_comments") or []
        top_comments = sorted(
            comments,
            key=lambda c: c.get("score", 0),
            reverse=True,
        )[:MAX_COMMENTS_PER_POST]

        for c in top_comments:
            body_text = (c.get("body", "") or "")[:MAX_COMMENT_BODY_CHARS]
            if not body_text:
                continue
            lines.append(
                f"  [{c.get('id', '')}] {c.get('author', '')} "
                f"score={c.get('score', 0)}:"
            )
            lines.append(f'  "{body_text}"')
            total_comments += 1

    context = "\n".join(lines)

    if len(context) > MAX_CONTEXT_CHARS:
        log.warn(
            f"[SUMMARIZER] Context is {len(context)} chars — truncating to "
            f"{MAX_CONTEXT_CHARS} to reduce risk of provider-side truncation/blocking"
        )
        context = context[:MAX_CONTEXT_CHARS]

    return context, total_comments

# ---------------------------------------------------------------------------
# Part caller — same pattern as query_generator.py's _call_part()
# ---------------------------------------------------------------------------
def _call_part(
    client,
    prompt: str,
    key: str | None,
    label: str,
    max_retries: int = LLM_MAX_RETRIES,
):
    """
    Call the LLM for one JSON section. Retries on call errors, empty
    responses, and JSON parse failures.

    - key=None   → returns the whole parsed dict on success.
    - key="..."  → returns data[key] if present; on the final attempt, if the
                   key is still missing, returns the parsed dict as a
                   best-effort fallback instead of discarding a response the
                   model *did* manage to produce.
    - Returns None once every attempt has failed — the caller decides what
      fallback to use, instead of this function raising and killing the run.
    """
    last_data = None
    for attempt in range(1, max_retries + 1):
        try:
            raw = client.call(_SYSTEM, prompt)
        except Exception as e:
            log.warn(f"[SUMMARIZER] {label} — LLM call error (attempt {attempt}/{max_retries}): {e}")
            continue

        if not raw:
            log.warn(
                f"[SUMMARIZER] {label} — empty response "
                f"(attempt {attempt}/{max_retries}, prompt_chars={len(prompt)})"
            )
            continue

        clean = re.sub(r"```json\s*|```\s*", "", raw).strip()
        clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL).strip()
        if not clean:
            log.warn(f"[SUMMARIZER] {label} — empty after stripping fences (attempt {attempt}/{max_retries})")
            continue

        try:
            data = json.loads(clean)
        except json.JSONDecodeError as e:
            log.warn(
                f"[SUMMARIZER] {label} — JSON parse error (attempt {attempt}/{max_retries}): {e}\n"
                f"Raw (first 400): {clean[:400]}"
            )
            continue

        if key is None:
            return data

        if isinstance(data, dict) and key in data:
            return data[key]

        last_data = data
        if attempt < max_retries:
            log.warn(f"[SUMMARIZER] {label} — response missing '{key}' (attempt {attempt}/{max_retries}), retrying...")
            continue

    if last_data is not None:
        log.warn(f"[SUMMARIZER] {label} — using best-effort parsed response (missing '{key}')")
        return last_data

    log.error(f"[SUMMARIZER] {label} — failed after {max_retries} attempts")
    return None

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def _prompt_discover_themes(query: str, context: str) -> str:
    return f"""You are a senior market research analyst specializing in extracting decision-ready insights from Reddit data.

User Query: "{query}"

Reddit Data:
{context}

Your task: Identify 3 to 5 DISTINCT, HIGH-VALUE themes that surface directly from the data and meaningfully help answer the query above.

Rules:
- Each theme must map to a concrete pattern, solution category, or recurring pain point visible in the data — not a generic topic area.
- Themes must NOT overlap. Each should represent a clearly different angle, approach, or problem dimension.
- Prioritize themes with the most signal (upvotes, repeated mentions, strong community agreement).
- Ignore off-topic posts and comments entirely.

Return ONLY this JSON — no markdown, no explanation:
{{
  "themes": [
    {{"id": "theme_1", "title": "<sharp, specific theme name>", "description": "<one sentence: what concrete pattern this theme captures and why it matters for the query>"}},
    {{"id": "theme_2", "title": "<sharp, specific theme name>", "description": "<one sentence: what concrete pattern this theme captures and why it matters for the query>"}}
  ]
}}"""


def _prompt_direct_answer(query: str, context: str) -> str:
    return f"""You are a warm, senior product researcher and consultant who has just spent hours deeply analyzing Reddit posts and comments on behalf of a client.
Your job is to deliver a direct, detailed answer to their question — grounded entirely in what Reddit users said — as if you are sitting across the table from them and giving your best professional advice.

User Query: "{query}"

Reddit Data:
{context}

Instructions:
- Write 3-5 warm, conversational sentences — like a trusted senior consultant giving a thorough, honest briefing.
- Sentence 1: Lead with the single strongest, most specific answer the Reddit data provides. Name actual tools, products, services, or methods users mention.
- Sentence 2: Add the most important nuance, caveat, or trade-off the community surfaces — what most people get wrong or overlook.
- Sentence 3: Explain WHY this is the answer — what patterns, volume of agreement, or strength of signal in the Reddit data makes you confident in this conclusion.
- Sentence 4-5 (optional): Surface any minority view, edge case, or context-dependent exception worth knowing.
- Ground every word in the Reddit data. Never answer from general knowledge. Never answer without Reddit evidence backing it.
- If the data does not contain enough relevant signal to answer confidently, return exactly: "We didn't find enough Reddit discussions that directly address this — the data available doesn't give us a confident answer for your query."

Return ONLY this JSON — no markdown, no explanation:
{{
  "direct_answer": "<3-5 warm, consultant-grade sentences grounded entirely in Reddit data, or the exact fallback message above>"
}}"""


def _prompt_overview(
    query: str,
    context: str,
    subreddits: list[str],
    now_iso: str,
    total_posts: int,
    total_comments: int,
    model_name: str,
    date_range: str,
) -> str:
    subs = ", ".join(f"r/{s}" for s in subreddits)
    return f"""You are a senior market research analyst. Analyze the Reddit data below and produce a structured overview.

User Query: "{query}"

Reddit Data:
{context}

Instructions:
- executive_summary: A neutral 3-5 sentence summary of what Reddit posts and comments broadly discuss — the topics, debates, opinions, and patterns present in the data. This is a digest of the conversation, not an answer to the query.

Return ONLY this JSON — no markdown, no explanation:
{{
  "query": "{query}",
  "subreddit": "multiple: {subs}",
  "analyzed_at": "{now_iso}",
  "executive_summary": "<3-5 sentence neutral digest of what Reddit broadly discusses in this data>",
  "overall_sentiment": "<positive|negative|neutral|mixed>",
  "total_signals": <integer: total posts + comments>,
  "market_signals": {{
    "brands_mentioned":    ["<every brand, product, app, or platform name found in the data>"],
    "demographic_signals": ["<specific user types: e.g. freelancers, expats, students, small business owners>"],
    "geographic_signals":  ["<specific locations, cities, countries, or regions mentioned>"],
    "emerging_topics":     ["<nascent trends, shifts, or patterns that appear in the data but aren't mainstream yet>"]
  }},
  "meta": {{
    "confidence":     "<High|Medium|Low>",
    "caveats":        "<note sample size, recency bias, subreddit skew, or other data limitations>",
    "total_posts":    {total_posts},
    "total_comments": {total_comments},
    "model":          "{model_name}",
    "date_range":     "{date_range}"
  }}
}}"""


def _prompt_theme(
    query: str,
    context: str,
    theme_id: str,
    theme_title: str,
    theme_desc: str,
) -> str:
    return f"""You are a senior market research analyst. Your task is to deeply analyze ONE specific theme from Reddit data and extract structured, actionable intelligence.

User Query: "{query}"

Theme to Analyze: "{theme_title}" — {theme_desc}

Reddit Data:
{context}

Focus EXCLUSIVELY on signals relevant to this theme. Ignore everything else.

Field-by-field instructions:
- summary: 2-3 sentences. Open with the most specific, concrete finding for this theme. Name actual tools, services, or methods users recommend. Close with the strongest community consensus or recurring advice.
- pain_points: Extract only real, recurring problems visible in multiple posts or highly-upvoted comments. Each pain point must include a verbatim quote from the data — never paraphrase or fabricate.
- user_suggested_solutions: Pull directly from what Reddit users recommend — be specific (name the tool, service, or exact method). Do not generalize.
- system_actions: Recommend concrete, implementable tools or services that address the pain point. "how" must be a practical 1-2 sentence roadmap, not a vague suggestion.

Return ONLY this JSON — no markdown, no explanation:
{{
  "id": "{theme_id}",
  "title": "{theme_title}",
  "summary": "<2-3 sentence specific finding as instructed above>",
  "sentiment": "<positive|negative|neutral|mixed>",
  "signal_count": <integer: number of posts+comments relevant to this theme>,
  "relevance_score": <integer 0-100: how directly this theme answers the query>,
  "brands_mentioned": ["<brands or platforms specifically associated with this theme>"],
  "demographic_signals": ["<user types who appear most in this theme>"],
  "pain_points": [
    {{
      "issue":         "<specific, concrete problem — not a generic category>",
      "severity":      "<High|Medium|Low>",
      "sentiment":     "<positive|negative|neutral|mixed>",
      "example_quote": "<VERBATIM quote copied exactly from the data — never invented>",
      "impact":        "<specific financial, operational, or human consequence of this problem>",
      "user_suggested_solutions": [
        "<exact solution Reddit users name — include tool/service/method name>",
        "<second distinct user-recommended solution — be specific>"
      ],
      "system_actions": [
        {{
          "action": "<specific SaaS tool, app, platform, automation, or service>",
          "why": "<one sentence: why this solves the problem, grounded in what Reddit users said>",
          "how": "<1-2 sentences: concrete steps to implement this today>"
        }}
      ]
    }}
  ]
}}

HARD RULES:
- All example_quote values must be copied VERBATIM from the provided data. Never paraphrase or fabricate.
- score and signal_count must be integers, not strings.
- severity must be exactly: High, Medium, or Low.
- sentiment must be exactly: positive, negative, neutral, or mixed.
- sources.kind must be exactly: post or comment.
- permalink = post URL + "/" + comment_id + "/"."""


def _prompt_actionable_next_steps(
    query: str,
    direct_answer: str,
    themes: list[dict],
) -> str:
    # collect only what reddit users themselves suggested — sole source of truth
    reddit_evidence = []
    for t in themes:
        for pp in t.get("pain_points", []):
            for solution in pp.get("user_suggested_solutions", []):
                reddit_evidence.append({
                    "solution": solution,
                    "theme":    t.get("title", ""),
                    "issue":    pp.get("issue", ""),
                })
    digest_json = json.dumps(reddit_evidence, indent=2)
    return f"""You are a senior market research analyst. You have completed a full Reddit analysis and already have the best answer to the user's query.

User Query: "{query}"

Direct Answer (this is what the user needs to accomplish):
"{direct_answer}"

Reddit User Suggestions (your only source of truth for actions — do not invent anything):
{digest_json}

Your job: produce a step-by-step action list that tells the user exactly HOW to accomplish the direct answer above.
Every single step must be backed by a Reddit user suggestion from the list above.
If a step cannot be traced back to a Reddit user suggestion, discard it.

Instructions:
- Steps should flow in logical execution order — what to do first, second, third.
- Each step must directly move the user toward accomplishing the direct answer.
- Name the exact tool, platform, service, or method Reddit users mentioned — never generalize.
- reddit_source: quote or paraphrase the specific Reddit user suggestion that backs this step — never leave empty.
- effort: realistic time estimate — e.g. "30 min", "2-3 hours", "half a day", "ongoing weekly."
- quick_win: true ONLY if a non-technical person can complete it in under 1 hour with zero budget.

Return ONLY this JSON — no markdown, no explanation:
{{
  "actionable_next_steps": [
    {{
      "priority":      <integer, 1 = do this first>,
      "step":          "<imperative verb phrase — exactly what to do>",
      "rationale":     "<1-2 sentences: how this step moves the user toward the direct answer>",
      "how":           "<2-3 sentences: exact implementation — name the tool, the first click, the order of operations>",
      "effort":        "<realistic time estimate>",
      "impact":        "<what specifically gets the user closer to accomplishing the direct answer>",
      "reddit_source": "<the Reddit user suggestion or community consensus that backs this step>",
      "quick_win":     <true|false>
    }}
  ]
}}"""

# ---------------------------------------------------------------------------
# Defaults filler — ensures all required fields present
# ---------------------------------------------------------------------------
def _fill_defaults(
    result: dict,
    query: str,
    model_name: str,
    total_posts: int,
    total_comments: int,
    now_iso: str,
) -> dict:
    result.setdefault("query",             query)
    result.setdefault("subreddit",         "reddit")
    result.setdefault("analyzed_at",       now_iso)
    result.setdefault("direct_answer",     "We didn't find enough Reddit discussions that directly address this — the data available doesn't give us a confident answer for your query.")
    result.setdefault("executive_summary", "")
    result.setdefault("overall_sentiment", "mixed")
    result.setdefault("total_signals",     total_posts + total_comments)
    result.setdefault("themes",            [])
    result.setdefault("market_signals", {
        "brands_mentioned":    [],
        "demographic_signals": [],
        "geographic_signals":  [],
        "emerging_topics":     [],
    })
    result.setdefault("actionable_next_steps", [])
    result.setdefault("meta", {
        "confidence":     "Medium",
        "caveats":        "",
        "total_posts":    total_posts,
        "total_comments": total_comments,
        "model":          model_name,
        "date_range":     "",
    })

    for i, theme in enumerate(result.get("themes", [])):
        theme.setdefault("id",                       f"theme_{i+1}")
        theme.setdefault("title",                    f"Theme {i+1}")
        theme.setdefault("summary",                  "")
        theme.setdefault("sentiment",                "mixed")
        theme.setdefault("signal_count",             0)
        theme.setdefault("relevance_score",          0)
        theme.setdefault("brands_mentioned",         [])
        theme.setdefault("demographic_signals",      [])
        theme.setdefault("pain_points",              [])
        theme.setdefault("quotes",                   [])
        theme.setdefault("sources",                  [])
        theme.setdefault("user_suggested_solutions", [])
        theme.setdefault("system_actions",           [])

    return result

# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------
def run_summarizer(
    posts: list[dict[str, Any]],
    user_query: str,
    client,
    user_profile: dict | None = None,
) -> dict[str, Any]:
    """
    Generate a structured JSON summary from gate4_passed (or user_approved) posts.
    Uses section-by-section LLM calls to prevent truncation:
      Call 0   → theme discovery
      Call 1   → direct answer (warm, consultant-grade, Reddit-only)
      Call 2   → overview + executive_summary + market_signals + meta
      Call 3…N → one theme per call
      Call N+1 → actionable_next_steps (ordered how-to steps grounded in Reddit user suggestions)
    """
    if not posts:
        log.warn("[SUMMARIZER] No posts provided — aborting")
        return {}

    now_iso    = datetime.now(timezone.utc).isoformat()
    model_name = client.model
    subreddits = list(dict.fromkeys(
        p.get("reddit_subreddit", "") for p in posts if p.get("reddit_subreddit")
    ))
    dates = [
        p.get("reddit_created_utc") for p in posts
        if p.get("reddit_created_utc")
    ]
    date_range     = f"{min(dates)} to {max(dates)}" if dates else "N/A"
    total_posts    = len(posts)
    context, total_comments = _build_context(posts)

    log.info(
        f"[SUMMARIZER] {total_posts} posts | {total_comments} comments | "
        f"context_chars={len(context)} | subreddits={subreddits}"
    )

    # ------------------------------------------------------------------ #
    # Call 0 — theme discovery                                            #
    # ------------------------------------------------------------------ #
    log.info("[SUMMARIZER] Call 0 — discovering themes...")
    themes_meta = _call_part(
        client, _prompt_discover_themes(user_query, context), "themes", "theme-discovery"
    )
    if not themes_meta:
        # Degrade instead of aborting the whole run — a single oversized or
        # flaky call shouldn't zero out an entire summarization.
        log.warn("[SUMMARIZER] Theme discovery failed after retries — falling back to one general theme")
        themes_meta = [{
            "id": "theme_1",
            "title": "General Discussion",
            "description": "General findings from the Reddit data relevant to the query.",
        }]
    else:
        log.info(f"[SUMMARIZER] {len(themes_meta)} themes: {[t.get('title', '?') for t in themes_meta]}")

    # ------------------------------------------------------------------ #
    # Call 1 — direct answer                                              #
    # ------------------------------------------------------------------ #
    log.info("[SUMMARIZER] Call 1 — direct answer...")
    direct_answer = "We didn't find enough Reddit discussions that directly address this — the data available doesn't give us a confident answer for your query."
    da = _call_part(client, _prompt_direct_answer(user_query, context), "direct_answer", "direct-answer")
    if da:
        direct_answer = da
        log.info(f"[SUMMARIZER] Direct answer — {direct_answer[:80]}...")
    else:
        log.warn("[SUMMARIZER] Direct answer failed after retries — using fallback message")

    # ------------------------------------------------------------------ #
    # Call 2 — overview                                                   #
    # ------------------------------------------------------------------ #
    log.info("[SUMMARIZER] Call 2 — overview...")
    overview = _call_part(client, _prompt_overview(
        user_query, context, subreddits, now_iso,
        total_posts, total_comments, model_name, date_range,
    ), None, "overview")
    if overview:
        log.info(
            f"[SUMMARIZER] Overview — "
            f"sentiment={overview.get('overall_sentiment')} | "
            f"confidence={overview.get('meta', {}).get('confidence')}"
        )
    else:
        # _fill_defaults() below fills every field an empty overview is
        # missing, so degrade rather than aborting the whole run.
        log.warn("[SUMMARIZER] Overview failed after retries — falling back to defaults")
        overview = {}

    # ------------------------------------------------------------------ #
    # Calls 3…N — one theme per call                                      #
    # ------------------------------------------------------------------ #
    themes = []
    for i, tm in enumerate(themes_meta):
        theme_title = tm.get("title", f"Theme {i+1}")
        theme_id    = tm.get("id", f"theme_{i+1}")
        log.info(f"[SUMMARIZER] Call {i+3} — theme: '{theme_title}'...")
        theme = _call_part(client, _prompt_theme(
            user_query, context,
            theme_id, theme_title, tm.get("description", ""),
        ), None, f"theme-{theme_id}")
        if theme:
            themes.append(theme)
            log.info(
                f"[SUMMARIZER] Theme '{theme_title}' — "
                f"sentiment={theme.get('sentiment')} | "
                f"signals={theme.get('signal_count')} | "
                f"pain_points={len(theme.get('pain_points', []))} | "
                f"quotes={len(theme.get('quotes', []))}"
            )
        else:
            log.warn(f"[SUMMARIZER] Theme '{theme_title}' failed after retries — skipping")

    # ------------------------------------------------------------------ #
    # Call N+1 — actionable next steps                                    #
    # ------------------------------------------------------------------ #
    actionable_next_steps = []
    if themes:
        log.info(f"[SUMMARIZER] Call {len(themes_meta)+3} — actionable next steps...")
        reddit_evidence = [
            solution
            for t in themes
            for pp in t.get("pain_points", [])
            for solution in pp.get("user_suggested_solutions", [])
        ]
        if not reddit_evidence:
            log.warn("[SUMMARIZER] Actionable next steps — no user_suggested_solutions found in themes, skipping")
        else:
            steps = _call_part(
                client,
                _prompt_actionable_next_steps(user_query, direct_answer, themes),
                "actionable_next_steps", "actionable-next-steps",
            )
            actionable_next_steps = steps or []
            if steps:
                log.info(f"[SUMMARIZER] Actionable next steps — {len(actionable_next_steps)} steps generated")
            else:
                log.warn("[SUMMARIZER] Actionable next steps failed after retries — skipping")

    # ------------------------------------------------------------------ #
    # Assemble                                                             #
    # ------------------------------------------------------------------ #
    result = {
        "query":             overview.get("query",             user_query),
        "subreddit":         overview.get("subreddit",         "reddit"),
        "analyzed_at":       overview.get("analyzed_at",       now_iso),
        "direct_answer":     direct_answer,
        "executive_summary": overview.get("executive_summary", ""),
        "overall_sentiment": overview.get("overall_sentiment", "mixed"),
        "total_signals":     overview.get("total_signals",     total_posts + total_comments),
        "themes":               themes,
        "market_signals":       overview.get("market_signals", {
            "brands_mentioned":    [],
            "demographic_signals": [],
            "geographic_signals":  [],
            "emerging_topics":     [],
        }),
        "actionable_next_steps": actionable_next_steps,
        "meta": overview.get("meta", {
            "confidence":     "Medium",
            "caveats":        "",
            "total_posts":    total_posts,
            "total_comments": total_comments,
            "model":          model_name,
            "date_range":     date_range,
        }),
    }

    result = _fill_defaults(result, user_query, model_name, total_posts, total_comments, now_iso)
    result = _repair(result)

    log.info(
        f"[SUMMARIZER] Complete — "
        f"{len(result['themes'])} themes | "
        f"sentiment={result['overall_sentiment']} | "
        f"confidence={result.get('meta', {}).get('confidence', '?')}"
    )
    return result