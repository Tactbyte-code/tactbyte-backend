import json
import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from src.core.settings import settings
from src.app.validate.model import ValidateQuery, ValidateQueryContext, ValidateQueryStatus
from src.core.database import AsyncSessionLocal
from src.infra.runpod.llm import get_client

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are an expert venture capitalist and market research analyst. "
    "Your sole job is to analyse startup ventures and generate structured market validation context. "
    "Return ONLY strict, valid JSON. Output MUST start with { and end with }. "
    "Do NOT wrap output in markdown, code fences, or add any explanatory text outside the JSON object."
)

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
            query_record.start_step(ValidateQueryStatus.VALIDATING)
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
            response = llm.call(_SYSTEM, user_prompt)

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
            query_record.complete_step(ValidateQueryStatus.SEARCHING)

            await db.commit()
            await db.refresh(context_record)

            logger.info(
                f"[_handle_validate_generate_context] Successfully completed context generation "
                f"for ValidateQuery ID: {query_id}. Generated {len(generated_signals)} search queries."
            )
            return context_record

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