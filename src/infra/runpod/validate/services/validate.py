import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.future import select

from src.core.settings import settings
from src.core.database import AsyncSessionLocal
from src.app.validate.model import (
    ValidateQuery, 
    ValidateQueryContext, 
    ValidateQueryStatus,
    ValidateMarketSource,
    ValidateScoreSummary
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

# ----------- business logic functions -------------
async def _handle_validate_generate_context(query_id: str) -> ValidateQueryContext:
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

            # Update status to VALIDATING
            # query_record.start_step(ValidateQueryStatus.VALIDATING)
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

            # 3. Build the user prompt (system prompt is passed separately to llm.call())
            user_prompt = f"""Analyse the following startup venture / feature idea and generate search queries and extraction anchors for market validation.

            Title: {query_record.title}
            Description: {query_record.description}
            Industry: {query_record.industry}
            Stage: {query_record.stage}

            Return ONLY this JSON — every field is required:
            {{
            "market_signals":  ["<targeted search query to find competitors, market size, or customer pain points>", "..."],
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

            # 4. Call LLM — pass system prompt + user prompt (matches LLMClient.call(system, prompt) signature)
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
            
            # FIX: Return a JSON-serializable dictionary
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

        # query_result = await db.execute(select(ValidateQuery).where(ValidateQuery.id == query_id))
        # query_record = query_result.scalars().first()
        # if query_record:
        #     query_record.start_step(ValidateQueryStatus.SEARCHING)
        #     await db.commit()
        #     logger.info(f"[VALIDATE][SEARCH] Query {query_id} status transitioned to SEARCHING.")

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
                    url=url,
                    snippet=r.get("snippet", ""),
                    doc_id=r.get("doc_id", ""),
                    user_approved=persisted_count < 10,
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
# PHASE 4: SUMMARIZATION & SCORING
# =====================================================================

async def _handle_validate_summary(query_id: str) -> dict[str, Any]:
    """
    Step 4: Fetches the venture details and scraped Vertex AI market data,
    invokes the LLM to generate a comprehensive institutional scorecard, 
    and saves it to ValidateScoreSummary.
    """
    logger.info(f"[_handle_validate_summary] Starting final summarization for Query ID: {query_id}")

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

            # 2. Fetch the market search data (top 15 approved sources)
            sources_result = await db.execute(
                select(ValidateMarketSource)
                .where(ValidateMarketSource.query_id == query_id)
                .where(ValidateMarketSource.user_approved == True)
            )
            sources = sources_result.scalars().all()

            # Format the sources into a readable string block for the LLM
            market_data_block = ""
            for i, src in enumerate(sources):
                market_data_block += f"[{i+1}] URL: {src.url}\nTitle: {src.title}\nInsight/Snippet: {src.snippet}\n\n"
            
            if not market_data_block.strip():
                market_data_block = "No external market data found. Rely on general industry knowledge."

            # 3. Initialize LLM
            llm = get_client(
                provider=settings.LLM_PROVIDER,
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_API_BASE_URL,
                max_tokens=8000, # Summaries need higher output limits
            )

            # 4. Construct the summary prompt enforcing the strict schema
            user_prompt = f"""
            Synthesize a comprehensive institutional validation report based on the following venture details and the raw market data provided below.

            --- VENTURE DETAILS ---
            Title: {query_record.title}
            Description: {query_record.description}
            Industry: {query_record.industry}
            Stage: {query_record.stage}

            --- RAW MARKET DATA SCRAPED ---
            {market_data_block}

            --- REQUIRED OUTPUT FORMAT ---
            You must output ONLY a raw JSON object matching the exact schema below. Do not add conversational text. 
            Evaluate the 6 dimensional scores critically on a scale of 1-10.
            Set 'signal_strength' to High, Medium, or Low based on how much concrete proof you found in the RAW MARKET DATA.

            {{
                "executive_verdict": "<2-3 candid sentences summarizing if this is a viable opportunity, needs a pivot, or is saturated>",
                "aggregate_score": <integer 0-100 based on overall viability>,
                "dimensional_scores": {{
                    "pain_point_severity": {{"score": <1-10>, "rationale": "<1-2 sentences referencing data>", "signal_strength": "<High/Medium/Low>"}},
                    "market_timing_and_size": {{"score": <1-10>, "rationale": "<1-2 sentences referencing data>", "signal_strength": "<High/Medium/Low>"}},
                    "competitive_defensibility": {{"score": <1-10>, "rationale": "<1-2 sentences referencing data>", "signal_strength": "<High/Medium/Low>"}},
                    "monetization_viability": {{"score": <1-10>, "rationale": "<1-2 sentences referencing data>", "signal_strength": "<High/Medium/Low>"}},
                    "landscape_saturation": {{"score": <1-10>, "rationale": "<1-2 sentences referencing data>", "signal_strength": "<High/Medium/Low>"}},
                    "execution_feasibility": {{"score": <1-10>, "rationale": "<1-2 sentences referencing data>", "signal_strength": "<High/Medium/Low>"}}
                }},
                "competitive_landscape": [
                    {{"name": "<Competitor Name>", "description": "<What they do>", "threat_level": "<High/Medium/Low>"}}
                ],
                "critical_vulnerabilities": [
                    "<String detailing top risk 1>",
                    "<String detailing top risk 2>"
                ],
                "actionable_next_steps": [
                    "<Stage-appropriate milestone 1>",
                    "<Stage-appropriate milestone 2>",
                    "<Stage-appropriate milestone 3>"
                ],
                "evidentiary_sources": [
                    "<Extract relevant URLs from the market data block that heavily influenced this report>"
                ]
            }}
            """

            logger.debug(f"[_handle_validate_summary] Invoking LLM for summary generation.")

            # 5. Call the LLM
            response = await llm.call(_SYSTEM_SUMMARY, user_prompt)

            # 6. Parse JSON safely
            cleaned = re.sub(r"```json\s*|```\s*", "", response).strip()
            cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

            try:
                parsed_data = json.loads(cleaned)
            except json.JSONDecodeError as json_err:
                logger.error(f"[_handle_validate_summary] Failed to parse JSON summary. Raw output:\n{response}")
                return await _fail_record(query_id, f"Failed to parse LLM summary JSON: {json_err}")

            # 7. Persist to ValidateScoreSummary Table
            summary_record = ValidateScoreSummary(
                query_id=query_id,
                executive_verdict=parsed_data.get("executive_verdict"),
                aggregate_score=parsed_data.get("aggregate_score"),
                dimensional_scores=parsed_data.get("dimensional_scores", {}),
                competitive_landscape=parsed_data.get("competitive_landscape", []),
                critical_vulnerabilities=parsed_data.get("critical_vulnerabilities", []),
                actionable_next_steps=parsed_data.get("actionable_next_steps", []),
                evidentiary_sources=parsed_data.get("evidentiary_sources", []),
                meta={
                    "provider": settings.LLM_PROVIDER,
                    "model": settings.LLM_MODEL,
                    "sources_used": len(sources)
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