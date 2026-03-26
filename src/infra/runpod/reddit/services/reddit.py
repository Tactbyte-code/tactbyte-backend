import runpod
from datetime import datetime, timezone
from src.core.settings import settings
from src.core.database import AsyncSessionLocal
from src.infra.runpod.llm import get_client
from src.app.reddit.model import RedditQuery, QueryStatus, FailureReason, RedditQueryContext, RedditSummary, RedditPost
from src.infra.runpod.reddit.services.query_generator import generate_queries
from src.infra.runpod.reddit.services.summarizer import run_summarizer
from src.infra.runpod.reddit.services.reddit_fetch import fetch_reddit_posts
from src.infra.runpod.reddit.services.vertex_search import run_vertex_search
from sqlalchemy import select

log = runpod.RunPodLogger()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def _get_record(query_id: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RedditQuery).where(RedditQuery.id == query_id)
        )
        return result.scalar_one_or_none()


async def _fail_record(query_id: str, reason: str = FailureReason.UNKNOWN) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RedditQuery).where(RedditQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if record:
            record.fail_step(reason)
            await db.flush()
            await db.commit()
    return {"statusCode": 500, "body": {"error": reason}}


# ─── Reddit search ────────────────────────────────────────────────────────────

async def _handle_reddit_search(query_id: str) -> dict:
    log.info(f"[REDDIT][SEARCH] Starting | query_id={query_id}")

    # 1. load record
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RedditQuery).where(RedditQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            log.error(f"[REDDIT][SEARCH] Query not found | query_id={query_id}")
            return {"statusCode": 404, "body": {"error": "Query not found"}}

        log.info(f"[REDDIT][SEARCH] Loaded record | query={record.query}")

        # 2. build LLM client
        client = get_client(
            provider=settings.LLM_PROVIDER,
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE_URL,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        log.info("[REDDIT][SEARCH] LLM client ready")

        # 3. generate context
        try:
            rich_context = generate_queries(
                user_query=           record.query,
                profile=              record.profile,
                conversation_history= record.conversation_history,
                client=               client,
            )
            log.info(f"[REDDIT][SEARCH] Context generated | queries={len(rich_context.get('queries', []))}")
        except Exception as e:
            log.error(f"[REDDIT][SEARCH] Query generation failed: {e}")
            record.fail_step(FailureReason.SEARCH_ERROR)
            await db.flush()
            await db.commit()
            return {"statusCode": 500, "body": {"error": f"Query generation failed: {e}"}}

        # 4. save context
        try:
            context_row = RedditQueryContext(
                query_id=      record.id,
                user_query=    record.query,
                queries=       rich_context.get("queries",        []),
                nlp_anchors=   rich_context.get("nlp_anchors",    []),
                topic_boundary=rich_context.get("topic_boundary", {}),
                schema_hints=  rich_context.get("schema_hints",   {}),
                provider=      rich_context.get("provider",       settings.LLM_PROVIDER),
                model=         rich_context.get("model",          settings.LLM_MODEL),
            )
            db.add(context_row)
            await db.flush()
            await db.commit()
            log.info(f"[REDDIT][SEARCH] Context saved | context_id={context_row.id}")
        except Exception as e:
            log.error(f"[REDDIT][SEARCH] Failed to save context: {e}")
            record.fail_step(FailureReason.UNKNOWN)
            await db.flush()
            await db.commit()
            return {"statusCode": 500, "body": {"error": f"Failed to save context: {e}"}}

    # ------------------------------------------------------------------ #
    # GATE 1 — Vertex AI Search                                           #
    # ------------------------------------------------------------------ #
    log.info("[GATE 1] Starting Vertex AI Search")
    try:
        vertex_results = await run_vertex_search(rich_context)
    except Exception as e:
        return await _fail_record(query_id, f"Vertex search failed: {e}")
    if not vertex_results:
        log.warn("[GATE 1] No results returned — aborting.")
        return await _fail_record(query_id, "No search results found.")
    log.info(f"[GATE 1] Complete — {len(vertex_results)} unique results")
    try:
        async with AsyncSessionLocal() as session:
            for r in vertex_results:
                post = RedditPost(
                    query_id=     query_id,
                    search_query= r.get("query", ""),
                    title=        r.get("title", ""),
                    url=          r.get("url", ""),
                    snippet=      r.get("snippet"),
                    doc_id=       r.get("doc_id"),
                )
                session.add(post)
            await session.commit()
    except Exception as e:
        log.error(f"[GATE 1] Failed to persist vertex results: {e}")
        return await _fail_record(query_id, str(e))
    log.info(f"[GATE 1] Persisted {len(vertex_results)} vertex results to DB")

    # ------------------------------------------------------------------ #
    # Mark search complete                                                 #
    # ------------------------------------------------------------------ #
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RedditQuery).where(RedditQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if record:
            record.status = QueryStatus.SEARCH_COMPLETE
            await db.commit()
            log.info(f"[REDDIT][SEARCH] Marked search complete | query_id={query_id}")

    return {"statusCode": 200}


# ─── Reddit summary ───────────────────────────────────────────────────────────
async def _handle_reddit_summary(query_id: str) -> dict:
    # log(f"[REDDIT][SUMMARY] Starting | query_id={query_id}")

    # 1. Load record
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RedditQuery).where(RedditQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            # log(f"[REDDIT][SUMMARY] Query not found | query_id={query_id}")
            return {"statusCode": 404, "body": {"error": "Query not found"}}
        user_query   = record.query
        user_profile = record.profile

    # 2. Duplicate summary check
    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            select(RedditSummary).where(RedditSummary.query_id == query_id)
        )
        if existing.scalar_one_or_none():
            # log(f"[REDDIT][SUMMARY] Duplicate detected | query_id={query_id}")
            return {"statusCode": 409, "body": {"error": "Summary already exists for this query"}}

    # 3. Guard: must not already be COMPLETED
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RedditQuery).where(RedditQuery.id == query_id)
        )
        record = result.scalar_one_or_none()
        if record.status == QueryStatus.COMPLETED:
            # log(f"[REDDIT][SUMMARY] Already COMPLETED | query_id={query_id}")
            return {"statusCode": 409, "body": {"error": "Summary already completed"}}

        # log(f"[REDDIT][SUMMARY] Marked SUMMARIZING | query_id={query_id}")

    # 4. Load user-approved RedditPost rows
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(RedditPost).where(
                    RedditPost.query_id      == query_id,
                    RedditPost.user_approved == True,
                )
            )
            approved_rows = result.scalars().all()
    except Exception as e:
        print(f"[REDDIT][SUMMARY] Failed to load approved posts: {e}")

    #data can be empty 
    print(f"[REDDIT][SUMMARY] {len(approved_rows)} approved posts loaded")

    # 5. Fetch Reddit .json for approved posts only
    try:
        vertex_results  = [{"url": row.url} for row in approved_rows]
        fetched_results = await fetch_reddit_posts(vertex_results=vertex_results)
    except Exception as e:
        print(f"[REDDIT][SUMMARY] Reddit fetch failed: {e}")
        return await _fail_record(query_id, FailureReason.SEARCH_ERROR)

    ok_count = sum(1 for r in fetched_results if r.get("reddit_fetch_ok"))
    print(f"[REDDIT][SUMMARY] Reddit fetch complete — {ok_count}/{len(fetched_results)} ok")

    # 6. Update approved RedditPost rows with fetched data
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(RedditPost).where(
                    RedditPost.query_id      == query_id,
                    RedditPost.user_approved == True,
                )
            )
            rows_to_update  = result.scalars().all()
            fetched_by_url  = {r["url"]: r for r in fetched_results}

            for row in rows_to_update:
                fetched = fetched_by_url.get(row.url)
                if fetched and fetched.get("reddit_fetch_ok"):
                    row.reddit_id           = fetched.get("reddit_id")
                    row.reddit_title        = fetched.get("reddit_title")
                    row.reddit_selftext     = fetched.get("reddit_selftext")
                    row.reddit_author       = fetched.get("reddit_author")
                    row.reddit_subreddit_id = fetched.get("reddit_subreddit_id")
                    row.reddit_subreddit    = fetched.get("reddit_subreddit")
                    row.reddit_score        = fetched.get("reddit_score")
                    row.reddit_url          = fetched.get("reddit_url")
                    row.reddit_created_utc  = _parse_dt(fetched.get("reddit_created_utc"))
                    row.reddit_comments     = fetched.get("reddit_comments") or []

            await db.commit()
        print(f"[REDDIT][SUMMARY] Updated {len(rows_to_update)} posts with Reddit data")
    except Exception as e:
        print(f"[REDDIT][SUMMARY] Failed to update posts with Reddit data: {e}")
        return await _fail_record(query_id, FailureReason.UNKNOWN)

    # 7. Build approved_posts payload for summarizer (from fetched data)
    approved_posts = [
        {
            "url":                 r.get("url"),
            "reddit_id":           r.get("reddit_id"),
            "reddit_title":        r.get("reddit_title"),
            "reddit_selftext":     r.get("reddit_selftext"),
            "reddit_author":       r.get("reddit_author"),
            "reddit_subreddit_id": r.get("reddit_subreddit_id"),
            "reddit_subreddit":    r.get("reddit_subreddit"),
            "reddit_score":        r.get("reddit_score"),
            "reddit_url":          r.get("reddit_url"),
            "reddit_created_utc":  r.get("reddit_created_utc"),
            "reddit_comments":     r.get("reddit_comments") or [],
        }
        for r in fetched_results
        if r.get("reddit_fetch_ok")
    ]

    if not approved_posts:
        print(f"[REDDIT][SUMMARY] No posts survived Reddit fetch | query_id={query_id}")

    # 8. Run summarizer
    client = get_client(
        provider=   settings.LLM_PROVIDER,
        model=      settings.LLM_MODEL,
        api_key=    settings.LLM_API_KEY,
        base_url=   settings.LLM_API_BASE_URL,
        max_tokens= settings.LLM_MAX_TOKENS,
    )

    try:
        final_output = run_summarizer(
            posts=        approved_posts,
            user_query=   user_query,
            client=       client,
            user_profile= user_profile,
        )
    except Exception as e:
        print(f"[REDDIT][SUMMARY] Summarization failed: {e}")
        return await _fail_record(query_id, FailureReason.SUMMARIZATION_ERROR)

    if not final_output:
        print(f"[REDDIT][SUMMARY] Empty output | query_id={query_id}")
        return await _fail_record(query_id, FailureReason.SUMMARIZATION_ERROR)

    print(
        f"[REDDIT][SUMMARY] Complete — "
        f"{len(final_output.get('themes', []))} themes | "
        f"sentiment={final_output.get('overall_sentiment')}"
    )

    # 9. Save summary + mark COMPLETED in one commit
    try:
        async with AsyncSessionLocal() as db:
            summary = RedditSummary(
                query_id=              query_id,
                search_query=          user_query,
                subreddit=             final_output.get("subreddit"),
                analyzed_at=           final_output.get("analyzed_at"),
                direct_answer=         final_output.get("direct_answer"),
                executive_summary=     final_output.get("executive_summary"),
                overall_sentiment=     final_output.get("overall_sentiment"),
                total_signals=         final_output.get("total_signals"),
                themes=                final_output.get("themes"),
                market_signals=        final_output.get("market_signals"),
                actionable_next_steps= final_output.get("actionable_next_steps"),
                meta=                  final_output.get("meta"),
            )
            db.add(summary)

            result = await db.execute(
                select(RedditQuery).where(RedditQuery.id == query_id)
            )
            record = result.scalar_one_or_none()
            if record:
                record.complete_step(QueryStatus.COMPLETED)

            await db.commit()
            print(f"[REDDIT][SUMMARY] Saved + marked COMPLETED | query_id={query_id}")
    except Exception as e:
        print(f"[REDDIT][SUMMARY] Failed to save summary: {e}")
        return await _fail_record(query_id, str(e))

    return {"statusCode": 200}