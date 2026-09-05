#!/usr/bin/env python3
"""
query_generator.py
─────────────────────────────────────────────────────────────────────────────
Generate Google-optimised Reddit search queries using a shared LLMClient.

Produces via 4 sequential micro-calls (each ~100 tokens — safe on tiny GPUs):
  • 3-5 Google-optimised reddit search queries
  • NLP anchors  (seed terms for semantic similarity scoring)
  • Topic boundary definitions  (what IS and IS NOT in scope)
  • Output schema field hints  (guide downstream summarize.py sections)

USAGE:
    from llm_client import get_client
    from query_generator import generate_queries

    client = get_client(settings=settings)
    result = generate_queries(
        user_query="best running shoes",
        profile={"role": "founder"},
        conversation_history=[{"role": "user", "content": "..."}],
        client=client,
    )
─────────────────────────────────────────────────────────────────────────────
"""

import json
import re

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════════
_SYSTEM = (
    "You are a Reddit research analyst. "
    "Return ONLY strict valid JSON. "
    "Output must start with { and end with }. "
    "No markdown, no code fences, no explanation, no trailing text."
)


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════
def _build_context(profile: dict = None, conversation_history: list = None) -> str:
    context = ""
    if profile:
        context += f"\nUser profile: {json.dumps(profile)}"
    if conversation_history:
        history_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}"
            for t in conversation_history
        )
        context += f"\nConversation history:\n{history_text}"
    return context


# ═══════════════════════════════════════════════════════════════════════════════
# PART PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════
def _prompt_queries(user_query: str, context: str = "") -> str:
    context_block = f"\nUser context (understand topic only, do NOT use these words in queries):\n{context}" if context else ""
    return f"""
You are a Reddit search expert. Convert a user query into simple Google search queries to find Reddit discussions.

User query: "{user_query}"{context_block}

Rules:
- Return ONLY valid JSON, no explanation, no markdown
- Up to 3 queries
- Every query MUST start with: site:reddit.com
- Keep queries SHORT: 2-3 keywords after site:reddit.com
- Use BROAD, common words only
- Do NOT copy words from context into queries

Example:
User query: "hi"
Context: user has been asking about flood damage detection using satellite imagery
Output:
{{"queries":[
  "site:reddit.com satellite flood detection",
  "site:reddit.com flood mapping open source",
  "site:reddit.com flood damage AI"
]}}

User query: "best budget mechanical keyboard"
Output:
{{"queries":[
  "site:reddit.com budget mechanical keyboard",
  "site:reddit.com mechanical keyboard recommendations",
  "site:reddit.com mechanical keyboard beginner"
]}}

Now generate for:
User query: "{user_query}"
Output:
"""


def _prompt_nlp(user_query: str, context: str = "") -> str:
    return f"""
You are a relevance filtering expert. Extract semantic signals from a user query so Reddit posts can be scored for relevance.

User query: "{user_query}"{context}

Generate terms across these signal types:
- Core concepts: the main topic keywords
- Synonyms & slang: how real Reddit users phrase the same thing
- Intent signals: words that reveal what the user wants (recommend, avoid, compare, fix, experience)
- Context signals: domain, setting, or situation specific to the user's profile and history

Rules:
- Return ONLY valid JSON, no explanation, no markdown
- 8 to 15 terms total, no duplicates
- 1 to 4 words each, no punctuation
- Tailor terms to the user's background and conversation context

Examples:
User query: "best budget mechanical keyboard"
Output:
{{"nlp_anchors": [
    "mechanical keyboard",
    "budget keyboard",
    "tactile switches",
    "clicky keys",
    "keycaps",
    "mech keys",
    "value pick",
    "entry level keyboard",
    "worth buying",
    "switch recommendation"
]}}

Now generate for:
User query: "{user_query}"
Output:
"""


def _prompt_boundary(user_query: str, context: str = "") -> str:
    return f"""
You are a content relevance expert. Define clear topic boundaries for filtering Reddit posts.

User query: "{user_query}"{context}

Define:
- in_scope: subtopics and contexts that ARE relevant to the user's query and background
- out_scope: subtopics and contexts that are clearly OFF-TOPIC or noise
- edge_cases: borderline topics that may or may not be relevant

Rules:
- Return ONLY valid JSON, no explanation, no markdown
- 3 to 6 items per list
- 1 to 4 words each, no punctuation
- Use profile and conversation history to define boundaries specific to this user
- No duplicates across any list

Examples:
User query: "best budget mechanical keyboard"
Output:
{{
  "topic_boundary": {{
    "in_scope":   ["budget keyboard picks", "switch type comparison", "typing experience review"],
    "out_scope":  ["membrane keyboards", "gaming mouse deals", "laptop keyboards"],
    "edge_cases": ["wireless keyboard budget", "keyboard for programming"]
  }}
}}

Now generate for:
User query: "{user_query}"
Output:
"""


def _prompt_schema(user_query: str, context: str = "") -> str:
    return f"""
You are a market research analyst. Extract structured signals from a user query for mining Reddit discussions.

User query: "{user_query}"{context}

Extract signals across these categories:
- brands_to_watch: companies, products, or tools likely mentioned in relevant discussions
- demographic_signals: user segments or personas likely discussing this — use profile to refine
- pain_point_categories: recurring frustrations this query touches on
- sentiment_drivers: specific factors that make users feel strongly positive or negative
- decision_factors: criteria users weigh when making a choice related to this query

Rules:
- Return ONLY valid JSON, no explanation, no markdown
- 3 to 6 items per list, no duplicates across any list
- 1 to 4 words each, no punctuation
- Tailor everything to the user's profile and conversation context

Examples:
User query: "best budget mechanical keyboard"
Output:
{{
  "schema_hints": {{
    "brands_to_watch":       ["Keychron", "Akko", "Royal Kludge", "Epomaker", "Nuphy"],
    "demographic_signals":   ["first time buyer", "office typist", "budget gamer", "programming student"],
    "pain_point_categories": ["wobbly stabilizers", "mushy stock switches", "poor software support"],
    "sentiment_drivers":     ["satisfying tactile feedback", "value for price", "flimsy build quality"],
    "decision_factors":      ["switch type", "price under 80", "hot swap support", "form factor"]
  }}
}}

Now generate for:
User query: "{user_query}"
Output:
"""


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK
# ═══════════════════════════════════════════════════════════════════════════════
def _mock_result(user_query: str) -> dict:
    q = user_query.lower().replace(" ", "+")
    return {
        "queries": [
            f"site:reddit.com {q} experience",
            f"site:reddit.com {q} recommendations",
            f"site:reddit.com {q} problems issues",
        ],
        "nlp_anchors": [
            user_query,
            f"{user_query} review",
            f"{user_query} problem",
            f"best {user_query}",
            f"{user_query} alternative",
        ],
        "topic_boundary": {
            "in_scope":  [f"direct {user_query} discussion", "user experience", "recommendations"],
            "out_scope": ["unrelated topics", "spam", "off-topic memes"],
        },
        "schema_hints": {
            "brands_to_watch":       ["MockBrand A", "MockBrand B"],
            "demographic_signals":   ["mock users", "test segment"],
            "pain_point_categories": ["mock pain point 1", "mock pain point 2"],
            "sentiment_drivers":     ["mock positive driver", "mock negative driver"],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
def _fallbacks(user_query: str) -> dict:
    return {
        "queries":        [f"site:reddit.com {user_query}"],
        "nlp_anchors":    [user_query],
        "topic_boundary": {"in_scope": [], "out_scope": []},
        "schema_hints":   {
            "brands_to_watch":       [],
            "demographic_signals":   [],
            "pain_point_categories": [],
            "sentiment_drivers":     [],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PART CALLER
# ═══════════════════════════════════════════════════════════════════════════════
def _call_part(client, prompt: str, key: str, log) -> dict | None:
    """
    Call the LLM for a single JSON key. Retries once on parse failure.
    Returns the VALUE at `key`, or None if both attempts fail.
    """
    for attempt in range(2):
        # try:
        #     raw = client.call(_SYSTEM, prompt)
        # except Exception as e:
        #     log(f"[Query Generator: Warning] LLM call error (attempt {attempt + 1}) for '{key}': {e}")
        #     continue

        try:
            raw = client.call(_SYSTEM, prompt)
        except Exception as e:
            log(f"[Query Generator: Warning] LLM call error (attempt {attempt + 1}) for '{key}': {e}")
            continue

        if not raw:
            log(f"[Query Generator: Warning] Empty response (attempt {attempt + 1}) for '{key}'")
            continue

        # Strip markdown fences and think blocks
        clean = re.sub(r"```json\s*|```\s*", "", raw).strip()
        clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL).strip()

        try:
            data = json.loads(clean)
        except json.JSONDecodeError as e:
            log(f"[Query Generator: Warning] JSON parse error (attempt {attempt + 1}) for '{key}': {e}")
            continue

        if isinstance(data, dict) and key in data:
            return data[key]
        if isinstance(data, dict) and attempt == 0:
            log(f"[Query Generator: Warning] Unexpected shape for '{key}' (attempt 1), retrying...")
            continue
        return data

    log(f"[Query Generator: Error] '{key}' failed after 2 attempts — using fallback")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════
def generate_queries(
    user_query: str,
    profile: dict = None,
    conversation_history: list = None,
    client=None,
    settings=None,
    verbose: bool = True,
) -> dict:
    """
    Generate Google-optimised Reddit search queries + NLP config.

    Args:
        user_query:           Natural-language research question
        profile:              User profile dict (role, background, etc.)
        conversation_history: List of {role, content} dicts from clarification
        client:               LLMClient instance. Auto-created if None.
        settings:             Pydantic Settings — used only when client is None.
        verbose:              Print progress.

    Returns:
        {
          "queries":        [...],
          "nlp_anchors":    [...],
          "topic_boundary": {"in_scope": [...], "out_scope": [...], "edge_cases": [...]},
          "schema_hints":   {
              "brands_to_watch": [...], "demographic_signals": [...],
              "pain_point_categories": [...], "sentiment_drivers": [...],
              "decision_factors": [...]
          }
        }
    """
    def log(msg):
        if verbose:
            print(msg, flush=True)

    # ── Resolve client ────────────────────────────────────────────────────────
    if client is None:
        from src.infra.runpod.llm import get_client
        client = get_client(settings=settings)

    is_mock = client.provider == "mock"
    log(f"[Query Generator] Generating queries for: \"{user_query}\"")
    log(f"[Query Generator] Provider: {client.provider} | Model: {client.model}" + (" (mock)" if is_mock else ""))
    if profile:
        log(f"[Query Generator] Profile: {json.dumps(profile)}")
    if conversation_history:
        log(f"[Query Generator] History turns: {len(conversation_history)}")

    # ── Build shared context ──────────────────────────────────────────────────
    context = _build_context(profile, conversation_history)

    # ── Call LLM (or mock) ────────────────────────────────────────────────────
    if is_mock:
        result = _mock_result(user_query)
        result["provider"] = client.provider
        result["model"]    = client.model
    else:
        fb = _fallbacks(user_query)

        log("[Query Generator] Part 1/4 — queries")
        queries = _call_part(client, _prompt_queries(user_query, context), "queries", log)

        log("[Query Generator] Part 2/4 — nlp_anchors")
        nlp = _call_part(client, _prompt_nlp(user_query, context), "nlp_anchors", log)

        log("[Query Generator] Part 3/4 — topic_boundary")
        boundary = _call_part(client, _prompt_boundary(user_query, context), "topic_boundary", log)

        log("[Query Generator] Part 4/4 — schema_hints")
        schema = _call_part(client, _prompt_schema(user_query, context), "schema_hints", log)

        def _to_list(val, fallback):
            if val is None:           return fallback
            if isinstance(val, dict): val = list(val.values())
            if isinstance(val, list):
                flat = []
                for item in val:
                    if isinstance(item, list): flat.extend(str(x) for x in item)
                    else:                      flat.append(str(item))
                return flat
            return fallback

        def _to_dict(val, fallback):
            if val is None:           return fallback
            if isinstance(val, dict): return val
            return fallback

        result = {
            "queries":        _to_list(queries,  fb["queries"]),
            "nlp_anchors":    _to_list(nlp,      fb["nlp_anchors"]),
            "topic_boundary": _to_dict(boundary, fb["topic_boundary"]),
            "schema_hints":   _to_dict(schema,   fb["schema_hints"]),
            "provider":       client.provider,
            "model":          client.model,
        }

        # Strip any double-quotes the model snuck into query strings
        result["queries"] = [str(q).replace('"', '') for q in result["queries"] if q]

        # Clamp to 1–4 queries
        if not result["queries"]:
            result["queries"].append(f"site:reddit.com {user_query}")
        result["queries"] = result["queries"][:4]

    # ── Print summary ─────────────────────────────────────────────────────────
    log(f"\n[Query Generator: Success] Generated {len(result['queries'])} queries:")
    for i, q in enumerate(result["queries"], 1):
        log(f"   {i}. {q}")

    anchors = result["nlp_anchors"]
    if isinstance(anchors, dict):
        anchors = list(anchors.values())
    result["nlp_anchors"] = anchors

    log(f"\n[Query Generator] NLP anchors ({len(anchors)}): {', '.join(anchors[:5])}")
    log(f"[Query Generator] In-scope:  {result['topic_boundary'].get('in_scope', [])}")
    log(f"[Query Generator] Out-scope: {result['topic_boundary'].get('out_scope', [])}")

    return result


def generate_query_strings(user_query: str, **kwargs) -> list:
    """Thin wrapper — returns only the list of query strings."""
    return generate_queries(user_query, **kwargs)["queries"]


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Google-optimised Reddit search queries via LLM"
    )
    parser.add_argument("query", help="Natural-language research question")
    parser.add_argument("-p", "--provider", default=None)
    parser.add_argument("-m", "--model",    default=None)
    parser.add_argument("-o", "--output",   default=None)
    args = parser.parse_args()

    from llm_client import get_client
    _client = get_client(provider=args.provider, model=args.model)

    result = generate_queries(args.query, client=_client)

    if args.output:
        from pathlib import Path
        Path(args.output).write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nSaved → {args.output}")
    else:
        print("\n" + json.dumps(result, indent=2, ensure_ascii=False))