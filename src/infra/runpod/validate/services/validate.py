import json
import logging
import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.future import select
import aiohttp
from bs4 import BeautifulSoup
from src.core.settings import settings
from src.core.database import AsyncSessionLocal
from src.app.validate.model import (
    ValidateQuery,
    ValidateQueryContext,
    ValidateQueryStatus,
    ValidateMarketSource,
    ValidateScoreSummary,
    ValidateSummarySource
)
from src.infra.runpod.llm import get_client
from src.infra.runpod.validate.services.vertex_search import run_vertex_search

logger = logging.getLogger(__name__)

_SYSTEM_CONTEXT = (
    "You are an expert venture capitalist and market research analyst. "
    "Your sole job is to analyse startup ventures and generate structured market validation context. "
    "Return ONLY strict, valid JSON. Output MUST start with { and end with }. "
    "Do NOT wrap output in markdown, code fences, or add any explanatory text outside the JSON object."
)

_SYSTEM_SUMMARY = (
    "You are a Tier-1 Venture Capital Partner and Expert Market Analyst. "
    "Your task is to ruthlessly evaluate a startup venture by synthesizing the founder's pitch with raw market data scraped from institutional sources (Vertex AI Search). "
    "Be highly analytical, objective, and brutally honest. Base your conclusions on the provided market data wherever possible. "
    "Return ONLY strict, valid JSON matching the exact requested schema. Output MUST start with { and end with }."
)

# ----------- helper functions -------------
async def _fail_record(query_id: str, reason: str) -> dict[str, Any]:
    """Helper to fail the query safely and return a 500 response."""
    logger.error(f"[VALIDATE][SEARCH] Failing record {query_id}: {reason}")
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))
            record = result.scalars().first()
            if record:
                record.fail_step(reason)
                await db.commit()
    except Exception as e:
        logger.error(f"Failed to update record status to FAILED: {e}")
    return {"statusCode": 500, "error": reason}

async def fetch_page_text(url: str, max_words: int = 800) -> str:
    """
    Fetches a URL and extracts the core readable HTML text on the fly.
    Uses browser spoofing headers to bypass basic bot protection.
    """
    # Standard desktop browser headers to bypass basic Cloudflare/WAF blocks
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return ""
                html = await response.text()
                
                soup = BeautifulSoup(html, "html.parser")
                
                # Strip out non-content elements
                for script in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                    script.extract()
                    
                text = soup.get_text(separator=" ", strip=True)
                words = text.split()[:max_words]
                
                return " ".join(words)
    except Exception as e:
        logger.warning(f"[fetch_page_text] Failed to scrape {url}: {e}")
        return ""

# ----------- business logic functions -------------
async def _handle_validate_generate_context(query_id: str) -> dict[str, Any]:
    """
    Step 2: Parses the venture details from ValidateQuery, invokes the LLM client instance to generate 
    search queries, market signals, NLP anchors, and topic boundaries, and stores 
    them in ValidateQueryContext using AsyncSessionLocal.
    """
    logger.info(f"[_handle_validate_generate_context] Starting context generation for ValidateQuery ID: {query_id}")

    async with AsyncSessionLocal() as db:
        try:
            # 1. Fetch the query record
            result = await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))
            query_record = result.scalars().first()
            
            if not query_record:
                logger.error(f"[_handle_validate_generate_context] ValidateQuery with id {query_id} not found in database.")
                raise ValueError(f"ValidateQuery with id {query_id} not found.")

            logger.debug(f"[_handle_validate_generate_context] Retrieved query record: title='{query_record.title}', industry='{query_record.industry}', stage='{query_record.stage}'")

            await db.commit()
            logger.info(f"[_handle_validate_generate_context] Query {query_id} status transitioned to VALIDATING.")

            # 2. Initialize LLM client
            logger.debug(f"[_handle_validate_generate_context] Initializing LLM client...")
            llm = get_client(
                provider=settings.LLM_PROVIDER,
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_API_BASE_URL,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
            
            # Extract location safely (with fallback if None)
            loc_data = (query_record.profile or {}).get("location", {})
            user_location = loc_data.get("city") or loc_data.get("country") or "Global"

            # ==========================================================
            # THE FIX: Enforcing Rigid Market-Hunting Query Archetypes
            # ==========================================================
            user_prompt = f"""Analyse the following startup venture / feature idea and generate strictly structured search queries for market validation.

            Title: {query_record.title}
            Description: {query_record.description}
            Industry: {query_record.industry}
            Stage: {query_record.stage}
            Target Region / Founder Location: {user_location}

            CRITICAL INSTRUCTION: Your 'market_signals' MUST NOT be conversational questions (e.g., do not write "what are the pain points of X"). 
            They must be Google-style advanced search queries designed to find institutional reports, financial data, and pricing.
            Always use negative keywords like "-quora -reddit -pinterest" to filter out user-generated junk.

            Return ONLY this JSON — every field is required:
            {{
            "market_signals": [
                "<1. Macro TAM Query: e.g., '{{Industry}} market size OR TAM CAGR 2024 -quora'>",
                "<2. Competitor Economics Query: e.g., '{{Top Competitor}} revenue OR pricing tiers OR ARR -reddit'>",
                "<3. Churn/Limitation Query: e.g., '{{Industry}} software limitations OR churn OR alternative -quora'>",
                "<4. Benchmark Query: e.g., '{{Industry}} SaaS benchmarks CAC LTV retention -reddit'>"
            ],
            "nlp_anchors":     ["<key technical or domain-specific keyword>", "..."],
            "topic_boundary":  {{
                "in_scope":       ["<area directly relevant to this venture>"],
                "adjacent":       ["<adjacent market worth watching>"],
                "out_of_scope":   ["<area explicitly excluded>"]
            }},
            "schema_hints":    {{
                "pricing_models":   ["<pricing pattern to look for>"],
                "competitor_names": ["<known competitor if any>"],
                "key_metrics":      ["<metric or data point to extract>"]
            }}
            }}"""

            logger.debug(f"[_handle_validate_generate_context] Invoking LLM for query {query_id}.")

            # 4. Call LLM — pass system prompt + user prompt
            response = llm.call(_SYSTEM_CONTEXT, user_prompt)

            logger.debug(f"[_handle_validate_generate_context] Received raw response from LLM (length: {len(response)} chars).")

            # 5. Parse JSON — strip markdown fences if present
            import re
            cleaned = re.sub(r"```json\s*|```\s*", "", response).strip()
            cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

            try:
                parsed_data = json.loads(cleaned)
                logger.info(f"[_handle_validate_generate_context] Successfully parsed JSON output from LLM for query {query_id}.")
            except json.JSONDecodeError as json_err:
                logger.error(f"[_handle_validate_generate_context] Failed to parse JSON response from LLM. Raw content was:\n{response}")
                raise json_err

            # 6. Save context into ValidateQueryContext
            context_record = ValidateQueryContext(
                query_id=query_record.id,
                market_signals=parsed_data.get("market_signals", []),
                nlp_anchors=parsed_data.get("nlp_anchors", []),
                topic_boundary=parsed_data.get("topic_boundary", {}),
                schema_hints=parsed_data.get("schema_hints", {}),
                provider=settings.LLM_PROVIDER,
                model=settings.LLM_MODEL,
            )
            db.add(context_record)

            # Store generated search queries on the main record and advance status
            generated_signals = parsed_data.get("market_signals", [])
            query_record.search_queries = generated_signals
            query_record.complete_step(ValidateQueryStatus.VALIDATED)

            await db.commit()
            await db.refresh(context_record)

            logger.info(
                f"[_handle_validate_generate_context] Successfully completed context generation "
                f"for ValidateQuery ID: {query_id}. Generated {len(generated_signals)} search queries."
            )
            
            return {
                "statusCode": 200,
                "message": "Context generated successfully",
            }

        except Exception as e:
            await db.rollback()
            logger.exception(f"[_handle_validate_generate_context] Error during context generation for ValidateQuery ID {query_id}: {str(e)}")
            if 'query_record' in locals() and query_record:
                try:
                    query_record.fail_step(str(e))
                    await db.commit()
                except Exception:
                    pass
            raise
        
async def _handle_validate_search(query_id: str) -> dict[str, Any]:
    """
    Step 3: Fetches market_signals from ValidateQueryContext, executes Vertex AI Search,
    persists results to ValidateMarketSource, and advances status to SCORING.
    """
    logger.info(f"[_handle_validate_search] Starting market search for Query ID: {query_id}")

    # 1. Fetch queries from context and transition status to SEARCHING
    async with AsyncSessionLocal() as db:
        context_result = await db.execute(
            select(ValidateQueryContext).where(ValidateQueryContext.query_id == query_id)
        )
        context_record = context_result.scalars().first()

        if not context_record or not context_record.market_signals:
            return await _fail_record(query_id, "No market signals/queries found. Context generation may have failed.")

        queries = context_record.market_signals

    # 2. Execute Vertex AI Search
    logger.info(f"[VALIDATE][SEARCH] Starting Vertex AI Search with {len(queries)} queries.")
    try:
        rich_context = {"queries": queries}
        vertex_results = await run_vertex_search(rich_context)
    except Exception as e:
        return await _fail_record(query_id, f"Vertex search failed: {e}")

    if not vertex_results:
        logger.warning("[VALIDATE][SEARCH] No results returned — aborting.")
        return await _fail_record(query_id, "No search results found.")

    logger.info(f"[VALIDATE][SEARCH] Complete — {len(vertex_results)} unique results")

    # 3. Persist results into ValidateMarketSource (with Deduplication)
    try:
        async with AsyncSessionLocal() as session:
            # Pre-fetch existing records from the database to handle function retries safely
            existing_records = await session.execute(
                select(ValidateMarketSource.search_query, ValidateMarketSource.url)
                .where(ValidateMarketSource.query_id == query_id)
            )
            
            # Initialize our tracking set with already-saved database records
            seen_keys = {(row.search_query, row.url) for row in existing_records}
            persisted_count = 0

            for r in vertex_results:
                search_query = r.get("query", "")
                url = r.get("url", "")
                
                dedup_key = (search_query, url)

                # Skip if we already saw this combination in the DB or earlier in this loop
                if dedup_key in seen_keys:
                    continue
                
                # Mark as seen
                seen_keys.add(dedup_key)

                market_source = ValidateMarketSource(
                    query_id=query_id,
                    search_query=search_query,
                    title=r.get("title", ""),
                    url=url
                )
                session.add(market_source)
                persisted_count += 1
                
            await session.commit()
            logger.info(f"[VALIDATE][SEARCH] Persisted {persisted_count} new market sources to DB (filtered out duplicates)")
            
    except Exception as e:
        logger.error(f"[VALIDATE][SEARCH] Failed to persist vertex results: {e}")
        return await _fail_record(query_id, f"Database persist failed: {e}")

    # 4. Mark search complete and advance status to SCORING
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ValidateQuery).where(ValidateQuery.id == query_id)
            )
            record = result.scalars().first()
            if record:
                record.complete_step(ValidateQueryStatus.SEARCH_COMPLETED)
                await db.commit()
                logger.info(f"[VALIDATE][SEARCH] Marked search complete | query_id={query_id} is now ready for SCORING")
    except Exception as e:
        logger.error(f"[VALIDATE][SEARCH] Failed to update query status to SCORING: {e}")
        return await _fail_record(query_id, f"Failed to mark query complete: {e}")

    return {
        "statusCode": 200,
        "message": "Search executed successfully",
    }

# =====================================================================
# PHASE 4: MAP-REDUCE SUMMARIZATION
# =====================================================================
async def _handle_validate_summary(query_id: str) -> dict[str, Any]:
    """
    Step 4: Fetches the venture details, filters junk domains, saves curated URLs 
    to ValidateSummarySource, scrapes URLs in parallel batches (Map), 
    synthesizes a calibrated scorecard (Reduce), and saves to ValidateScoreSummary.
    """
    logger.info(f"[_handle_validate_summary] Starting Map-Reduce summarization for Query ID: {query_id}")

    async with AsyncSessionLocal() as db:
        try:
            # 1. Fetch the main query
            result = await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))
            query_record = result.scalars().first()
            if not query_record:
                return await _fail_record(query_id, f"ValidateQuery with id {query_id} not found.")

            # Update status
            query_record.start_step(ValidateQueryStatus.SCORING)
            await db.commit()
            logger.info(f"[VALIDATE][SUMMARY] Query {query_id} status transitioned to SCORING.")

            # 2. Fetch ALL market search data
            sources_result = await db.execute(
                select(ValidateMarketSource)
                .where(ValidateMarketSource.query_id == query_id)
            )
            sources = sources_result.scalars().all()
            
            logger.info(f"[_handle_validate_summary] Extracted {len(sources)} raw sources from DB.")

            # ==========================================================
            # PRE-SCRAPE NOISE FILTERING & SAVING TO SUMMARY SOURCES
            # ==========================================================
            BANNED_DOMAINS = [
                "prnewswire.com", 
                "globenewswire.com", 
                "businesswire.com", 
                "medium.com",
                "yahoo.com",
                "seekingalpha.com",
                "crunchbase.com",
                # New SEO/UGC junk to block:
                "quora.com",
                "reddit.com",
                "forbes.com/sites", # Forbes contributor network is mostly garbage
                "techcrunch.com"    # Usually just funding announcements, not TAM/metrics
            ]
            BANNED_EXTENSIONS = [".pdf", ".ppt", ".pptx", ".doc", ".docx"]

            clean_sources = []
            for src in sources:
                url_lower = src.url.lower()
                
                # Reject PDFs/documents and press release mills
                if any(url_lower.endswith(ext) or f"{ext}?" in url_lower for ext in BANNED_EXTENSIONS):
                    continue
                if any(domain in url_lower for domain in BANNED_DOMAINS):
                    continue
                    
                clean_sources.append(src)

            # Take only the top 15 clean sources for maximum relevance
            sources = clean_sources[:15] 
            
            logger.info(f"[_handle_validate_summary] Filtered down to {len(sources)} clean sources. Persisting to ValidateSummarySource...")

            # Persist these chosen URLs to ValidateSummarySource
            for i, src in enumerate(sources):
                summary_source = ValidateSummarySource(
                    query_id=query_id,
                    title=src.title,
                    url=src.url,
                    scrape_order=i
                )
                db.add(summary_source)
            
            # Commit the insertion of Summary Sources before moving to LLM phase
            await db.commit()
            
            # 3. Initialize LLM
            llm = get_client(
                provider=settings.LLM_PROVIDER,
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_API_BASE_URL,
                max_tokens=8000, 
            )

            # ==========================================================
            # THE "MAP" PHASE: Parallel Batch Scraping & Fact Extraction
            # ==========================================================
            batch_size = 5
            source_batches = [sources[i:i + batch_size] for i in range(0, len(sources), batch_size)]
            
            extracted_market_facts = ""
            total_batches = len(source_batches)

            # --- THE FIX: Create a safe wrapper to guarantee strings are returned ---
            async def safe_fetch(url: str) -> str:
                try:
                    result = await fetch_page_text(url)
                    # Ensure we always return a string
                    return result if isinstance(result, str) else ""
                except Exception as e:
                    logger.warning(f"[_handle_validate_summary] safe_fetch failed for {url}: {e}")
                    return ""
            # ------------------------------------------------------------------------

            for index, batch in enumerate(source_batches):
                batch_num = index + 1
                logger.info(f"[_handle_validate_summary] [MAP PHASE] Starting extraction for Batch {batch_num}/{total_batches} ({len(batch)} URLs).")
                
                # Run the scraper asynchronously for all 5 URLs
                scrape_tasks = [safe_fetch(src.url) for src in batch]
                
                # We can remove return_exceptions=True because safe_fetch catches everything
                scraped_contents = await asyncio.gather(*scrape_tasks)

                batch_text_block = ""
                for src, content in zip(batch, scraped_contents):
                    if content and content.strip():
                        batch_text_block += f"Source: {src.title}\nURL: {src.url}\nContent: {content}\n\n"

                if not batch_text_block:
                    logger.warning(f"[_handle_validate_summary] [MAP PHASE] Batch {batch_num}/{total_batches} yielded no readable content. Skipping extraction.")
                    continue

                extraction_prompt = f"""
                Extract the hard facts from the following raw market data regarding this venture: {query_record.title} ({query_record.industry}).
                
                CRITICAL INSTRUCTION: You must aggressively hunt for and extract exact numbers, statistics, percentages, and dollar amounts. Do not summarize a number (e.g. say "$45.5B", not "a large market").
                
                Identify:
                - Exact Market Size & Growth metrics (e.g., $X Billion, Y% CAGR)
                - Competitor Names & their scale (e.g., funding rounds, user counts)
                - Exact Pricing Data (e.g., $20/mo, 2.5% transaction fee)
                - Quantifiable Customer Pain Points (e.g., "takes 4 hours", "loses 15% revenue")
                - NEW: Look for estimated time to build software, and total number of competitors in the space.
                
                Keep it strictly to bullet points. Do not invent data. If no relevant data exists in this batch, output exactly "NO_FACTS".
                
                RAW BATCH DATA:
                {batch_text_block}
                """
                
                logger.debug(f"[_handle_validate_summary] [MAP PHASE] Invoking LLM fact extraction for Batch {batch_num}/{total_batches}...")
                
                batch_facts = llm.call(_SYSTEM_SUMMARY, extraction_prompt).strip()
                
                if batch_facts and "NO_FACTS" not in batch_facts:
                    extracted_market_facts += f"\n--- Batch {batch_num} Facts ---\n{batch_facts}\n"
                    logger.info(f"[_handle_validate_summary] [MAP PHASE] Successfully extracted facts for Batch {batch_num}/{total_batches}.")
                else:
                    logger.info(f"[_handle_validate_summary] [MAP PHASE] LLM found no relevant facts in Batch {batch_num}/{total_batches}.")


            # ==========================================================
            # THE "REDUCE" PHASE: Final Scoring based on Extracted Facts
            # ==========================================================
            # LOGIC BUG FIXED: Direct empty string check
            if not extracted_market_facts.strip():
                logger.warning(f"[_handle_validate_summary] No facts extracted for Query ID {query_id} across all batches!")
                extracted_market_facts = "No concrete external market data found. Rely on general industry knowledge."

            logger.debug(f"[_handle_validate_summary] Consolidated Market Facts Preview:\n{extracted_market_facts[:1000]}...")
            
            loc_data = (query_record.profile or {}).get("location", {})
            user_location = loc_data.get("city") or loc_data.get("country") or "Global"

            final_user_prompt = f"""
            Synthesize a comprehensive institutional validation report based on the following venture details and the extracted market facts.

            --- VENTURE DETAILS ---
            Title: {query_record.title}
            Description: {query_record.description}
            Industry: {query_record.industry}
            Stage: {query_record.stage}
            Target Geography: {user_location}

            --- EXTRACTED MARKET FACTS ---
            {extracted_market_facts}

            --- SCORING CALIBRATION RULES (CRITICAL) ---
            Do not cluster scores in the middle (4-6) defensively. Use the full 1-10 scale based on this exact rubric:
            - 1-3: Fatal flaw. Saturated market, free competitors, or massive execution barriers.
            - 4-6: Average venture. Standard competition, proven but competitive market size.
            - 7-8: Strong signal. Clear differentiator, growing TAM, or highly fragmented weak incumbents.
            - 9-10: Exceptional. Monopolistic potential, desperate customer pain point with no clear solution.
            
            If the data proves the market is growing and competitors are flawed, you MUST award scores of 7+. Do not penalize the idea just because it is early-stage.

            --- REQUIRED OUTPUT FORMAT ---
            You must output ONLY a raw JSON object matching the exact schema below. Do not add conversational text. 
            Evaluate the 6 dimensional scores critically on a scale of 1-10.
            Set 'signal_strength' to High, Medium, or Low based on how much concrete proof you found in the EXTRACTED MARKET FACTS.

            RULE 1: You must aggressively inject the hard statistics, dollar amounts, and percentages from the market facts directly into your rationales.
            RULE 2: If the extracted market facts are sparse, rely on logical deduction and industry benchmarks. DO NOT penalize the venture with low scores (3-5) just because the provided data block was short.

            {{
                "executive_verdict": "<8-9 candid sentences summarizing if this is a viable opportunity. Include top-level market size stats.>",
                "aggregate_score": <MUST be the exact mathematical sum of your 6 dimensional scores divided by 60, then multiplied by 100. (e.g., if dimensions sum to 42, score is 70)>,
                "dimensional_scores": {{
                    "pain_point_severity": {{
                        "score": <1-10>, 
                        "rationale": "<4-5 sentences.>", 
                        "signal_strength": "<High/Medium/Low>",
                        "key_metric": {{
                            "label": "Est. Revenue/Time Wasted", 
                            "value": <float or null>, 
                            "unit": "<% or hrs>",
                            "chart_data": [
                                {{"name": "This Venture", "value": <float or null>}},
                                {{"name": "Industry Avg", "value": <float or null>}},
                                {{"name": "Legacy Tool", "value": <float or null>}}
                            ]
                        }}
                    }},
                    "market_timing_and_size": {{
                        "score": <1-10>, 
                        "rationale": "<4-5 sentences.>", 
                        "signal_strength": "<High/Medium/Low>",
                        "key_metric": {{
                            "label": "Total Addressable Market", 
                            "value": <float or null>, 
                            "unit": "<$B>",
                            "chart_data": [
                                {{"name": "This Venture", "value": <float or null>}},
                                {{"name": "Industry Target", "value": <float or null>}},
                                {{"name": "Top Incumbent", "value": <float or null>}}
                            ]
                        }}
                    }},
                    "competitive_defensibility": {{
                        "score": <1-10>, 
                        "rationale": "<4-5 sentences.>", 
                        "signal_strength": "<High/Medium/Low>",
                        "key_metric": {{
                            "label": "Top Incumbent Funding/Share", 
                            "value": <float or null>, 
                            "unit": "<$M or %>",
                            "chart_data": [
                                {{"name": "This Venture", "value": <float or null>}},
                                {{"name": "Average Startup", "value": <float or null>}},
                                {{"name": "Top Incumbent", "value": <float or null>}}
                            ]
                        }}
                    }},
                    "monetization_viability": {{
                        "score": <1-10>, 
                        "rationale": "<4-5 sentences.>", 
                        "signal_strength": "<High/Medium/Low>",
                        "key_metric": {{
                            "label": "Avg Industry ARPU", 
                            "value": <float or null>, 
                            "unit": "<$>",
                            "chart_data": [
                                {{"name": "This Venture", "value": <float or null>}},
                                {{"name": "Industry Avg", "value": <float or null>}},
                                {{"name": "Top Incumbent", "value": <float or null>}}
                            ]
                        }}
                    }},
                    "landscape_saturation": {{
                        "score": <1-10>, 
                        "rationale": "<4-5 sentences.>", 
                        "signal_strength": "<High/Medium/Low>",
                        "key_metric": {{
                            "label": "Established Competitors", 
                            "value": <integer or null>, 
                            "unit": "<count>",
                            "chart_data": [
                                {{"name": "This Venture", "value": <integer or null>}},
                                {{"name": "Direct Peers", "value": <integer or null>}},
                                {{"name": "Total Category", "value": <integer or null>}}
                            ]
                        }}
                    }},
                    "execution_feasibility": {{
                        "score": <1-10>, 
                        "rationale": "<4-5 sentences.>", 
                        "signal_strength": "<High/Medium/Low>",
                        "key_metric": {{
                            "label": "Est. Time to MVP", 
                            "value": <float or null>, 
                            "unit": "<months>",
                            "chart_data": [
                                {{"name": "This Venture", "value": <float or null>}},
                                {{"name": "Industry Avg", "value": <float or null>}},
                                {{"name": "Enterprise Build", "value": <float or null>}}
                            ]
                        }}
                    }}
                }},
                "competitive_landscape": [
                    {{
                        "name": "<Competitor Name>",
                        "scope": "<Local / Regional / Global>",
                        "description": "<What they do in 1 sentence. Include presence in {user_location} if local.>",
                        "target_segment": "<Enterprise / SMB / Solo>",
                        "pricing_model": "<Exact pricing tiers>",
                        "core_weakness": "<Their biggest flaw based on the data>",
                        "how_to_differentiate": "<Actionable differentiation strategy>",
                        "threat_level": "<High/Medium/Low>"
                    }}
                ],
                "critical_vulnerabilities": [
                    "<String detailing top risk 1>",
                    "<String detailing top risk 2>",
                    "<String detailing top risk 3>",
                    "<String detailing top risk 4>",
                    "<String detailing top risk 5>",
                ],
                "actionable_next_steps": [
                    "<Stage-appropriate milestone 1>",
                    "<Stage-appropriate milestone 2>",
                    "<Stage-appropriate milestone 3>",
                    "<Stage-appropriate milestone 4>",
                    "<Stage-appropriate milestone 5>",
                ],
            }}
            """

            logger.info(f"[_handle_validate_summary] Invoking LLM for final REDUCE summary generation.")
            final_response = llm.call(_SYSTEM_SUMMARY, final_user_prompt)

            # 6. Parse JSON safely
            cleaned = re.sub(r"```json\s*|```\s*", "", final_response).strip()
            cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

            try:
                parsed_data = json.loads(cleaned)
            except json.JSONDecodeError as json_err:
                logger.error(f"[_handle_validate_summary] Failed to parse JSON summary. Raw output:\n{final_response}")
                return await _fail_record(query_id, f"Failed to parse LLM summary JSON: {json_err}")

            # Extract URLs for UI payloads based on the 15 clean sources used
            extracted_urls = [src.url for src in sources]
            
            # Prepare the all_sources list
            all_sources_data = [{"title": src.title, "url": src.url} for src in sources]

            # 7. Persist to ValidateScoreSummary Table
            summary_record = ValidateScoreSummary(
                query_id=query_id,
                executive_verdict=parsed_data.get("executive_verdict"),
                aggregate_score=parsed_data.get("aggregate_score"),
                dimensional_scores=parsed_data.get("dimensional_scores", {}),
                competitive_landscape=parsed_data.get("competitive_landscape", []),
                critical_vulnerabilities=parsed_data.get("critical_vulnerabilities", []),
                actionable_next_steps=parsed_data.get("actionable_next_steps", []),
                evidentiary_sources=extracted_urls[:5], # Top 5 for main UI reference
                all_sources=all_sources_data, # All 15 clean sources for UI display
                meta={
                    "provider": settings.LLM_PROVIDER,
                    "model": settings.LLM_MODEL,
                    "sources_used": len(sources),
                    "batches_processed": len(source_batches)
                }
            )
            db.add(summary_record)

            # 8. Mark the entire pipeline as COMPLETED
            query_record.complete_step(ValidateQueryStatus.COMPLETED)
            
            await db.commit()
            logger.info(f"[_handle_validate_summary] Successfully generated and saved summary for Query ID {query_id}.")

            return {
                "statusCode": 200,
                "message": "Validation pipeline completed successfully",
                "summary_id": str(summary_record.id)
            }

        except Exception as e:
            await db.rollback()
            logger.exception(f"Error during summarization for Query ID {query_id}: {str(e)}")
            return await _fail_record(query_id, str(e))