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
    ValidateSummarySource,
    ValidateQueryEvidence
)
from src.infra.runpod.llm import get_client
from src.infra.runpod.validate.services.vertex_search import run_vertex_search
from src.infra.runpod.validate.services.search_collectors import (
    fetch_macro_indicators,
    fetch_community_discussions,
    # fetch_vertex_search,
)

logger = logging.getLogger(__name__)

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
async def _handle_validate_search(query_id: str) -> dict:
    logger.info(f"[_handle_validate_search] Starting parallel search for Query ID: {query_id}")

    async with AsyncSessionLocal() as db:
        # ==========================================
        # 1. READ DB ONCE (Get the Research Plan)
        # ==========================================
        query_stmt = select(ValidateQuery).where(ValidateQuery.id == query_id)
        query_record = (await db.execute(query_stmt)).scalars().first()

        context_stmt = select(ValidateQueryContext).where(ValidateQueryContext.query_id == query_id)
        context_record = (await db.execute(context_stmt)).scalars().first()

        if not query_record or not context_record:
            raise ValueError(f"Missing records for query {query_id} to proceed with Stage 3.")

        plan = context_record.research_plan or {}
        country_code = plan.get("country_iso2")
        
        # Extract sections from the plan
        pain_inputs = plan.get("pain", {})
        market_inputs = plan.get("market", {})
        comp_inputs = plan.get("competition", {})
        risk_inputs = plan.get("risk", {})
        cost_inputs = plan.get("cost", {})

        # ==========================================
        # 2. MAP JSON LISTS TO THE 9 PARAMETERS
        # ==========================================
        
        # 1. Pain: Combine complaints and alternative lookups
        pain_queries = pain_inputs.get("complaint_queries", []) + pain_inputs.get("alternative_queries", [])
        
        # 2. Market: Combine institutional sizing and indicator terms
        market_queries = market_inputs.get("institutional_queries", []) + market_inputs.get("indicator_search_terms", [])
        
        # 3. Demand: Cross-pollinate industry keywords with pain complaints
        demand_queries = market_inputs.get("industry_keywords", []) + pain_inputs.get("complaint_queries", [])
        
        # 4. Competition: Discovery and competitor names
        comp_queries = comp_inputs.get("discovery_queries", []) + pain_inputs.get("competitor_app_terms", [])
        
        # 5. Unit Economics: Pricing queries and bottom-up variables
        unit_econ_queries = comp_inputs.get("pricing_queries", []) + market_inputs.get("bottom_up_variables", [])
        
        # 6. Cost: Licence queries and tech stack costs
        cost_queries = cost_inputs.get("licence_queries", [])
        
        # 7. Regulatory: Strict legal/compliance queries
        regulatory_queries = risk_inputs.get("regulatory_queries", [])
        
        # 8. Survival/Funding: Sector survival terms and grants/funding
        survival_queries = risk_inputs.get("funding_queries", []) + risk_inputs.get("survival_sector_terms", [])

        # ==========================================
        # 3. FIRE ALL APIs IN PARALLEL
        # ==========================================
        tasks = [
            # Macro (Parameter 9 - DBnomics uses the query_id to get the ISO code internally)
            fetch_macro_indicators(country_code),
            
            # Community/HN (Focuses strictly on human complaints and organic demand)
            fetch_community_discussions("pain_point_severity", pain_queries),
            fetch_community_discussions("demand_signals", demand_queries),
            
            # Vertex Search (Scrapes institutional web, reports, and pricing pages)
            fetch_vertex_search("pain_point_severity", pain_queries),
            fetch_vertex_search("market_timing_and_size", market_queries),
            fetch_vertex_search("demand_signals", demand_queries),
            fetch_vertex_search("competitive_defensibility", comp_queries),
            fetch_vertex_search("monetization_viability", unit_econ_queries),
            fetch_vertex_search("execution_feasibility", cost_queries),      # Maps to Cost/Execution
            fetch_vertex_search("feasibility_regulatory", regulatory_queries),
            fetch_vertex_search("survival_funding", survival_queries)
        ]

        logger.info(f"[_handle_validate_search] Dispatched {len(tasks)} parallel collection workers.")
        
        collected_batches = await asyncio.gather(*tasks, return_exceptions=True)

        # ==========================================
        # 4. FLATTEN, DEDUPLICATE, AND WRITE TO DB ONCE
        # ==========================================
        db_records = []
        seen_urls = set()

        for batch in collected_batches:
            if isinstance(batch, Exception):
                logger.error(f"[_handle_validate_search] A sub-task failed: {batch}")
                continue

            for item in batch:
                # Deduplicate based on the exact URL and the parameter it belongs to
                # We use dictionary access because the fetchers now return .to_dict() JSON objects
                dedup_key = f"{item['parameter']}:{item['source_url']}"
                if dedup_key in seen_urls:
                    continue
                
                seen_urls.add(dedup_key)

                db_records.append(
                    ValidateQueryEvidence(
                        query_id=query_record.id,
                        parameter=item["parameter"],
                        source_type=item["source_type"],
                        source_url=item["source_url"],
                        title=item.get("title"),
                        raw_content=item["raw_content"],
                        metadata_=item.get("metadata", {}),
                        retrieved_at=item["retrieved_at"],
                    )
                )

        if db_records:
            db.add_all(db_records)

        query_record.status = ValidateQueryStatus.SEARCH_COMPLETED
        await db.commit()

        logger.info(f"[_handle_validate_search] Saved {len(db_records)} evidence rows for {query_id}.")

        return {
            "statusCode": 200,
            "query_id": query_id,
            "evidence_count": len(db_records),
            "parameters_covered": list({r.parameter for r in db_records}),
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
                - Competitor Names, their scale, AND their official website URLs if mentioned.
                - Exact Pricing Data (e.g., $20/mo, 2.5% transaction fee)
                - Quantifiable Customer Pain Points (e.g., "takes 4 hours", "loses 15% revenue")
                - Look for estimated time to build software, and total number of competitors in the space.
                
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
                    # ---> ADD THIS STRICT LIMIT INSTRUCTION <---
                    # "LIMIT: Extract a maximum of 5 to 8 of the most prominent competitors explicitly named in the market facts. Do not list more than 8."
                    {{
                        "name": "<Competitor Name>", 
                        "website_url": "<Official URL (e.g., https://www.competitor.com). Infer standard .com if not explicitly in text.>",
                        "scope": "<Local / Regional / Global>",
                        "description": "<What they do in 1 sentence. Include presence in {user_location} if local.>", 
                        "target_segment": "<Who their ideal customer is (e.g., Enterprise, SMB, Solo)>",
                        "pricing_model": "<Exact pricing tiers (e.g., Freemium + $19/mo, 2.9% + 30¢)>",
                        "core_weakness": "<Their biggest flaw or top user complaint based on the data>",
                        "how_to_differentiate": "<1 actionable sentence on how this venture can beat them>",
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