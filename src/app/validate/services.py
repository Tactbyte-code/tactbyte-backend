import logging
import math
import copy
from uuid import UUID
from typing import Dict, Any
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.validate.model import ValidateQuery, ValidateQueryStatus, ValidateQueryResult
from src.app.onboarding.model import Onboarding
from src.app.user.model import User
from src.app.validate.schema import ValidateQueryInput
from src.infra.runpod.client import trigger as runpod_trigger

logger = logging.getLogger(__name__)

SECTION_CREDITS = 22
PRIORITY_KEYS = ["pain", "demand", "unit_economics"]

# ------------ helper functions -------------
async def _get_query_or_404(query_id: UUID, user_id: int, db: AsyncSession) -> ValidateQuery:
    result = await db.execute(
        select(ValidateQuery).where(
            ValidateQuery.id      == query_id,
            ValidateQuery.user_id == user_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    return record

async def get_status(query_id: UUID, user_id: int, db: AsyncSession) -> ValidateQuery:
    result = await db.execute(
        select(ValidateQuery).where(
            ValidateQuery.id      == query_id,
            ValidateQuery.user_id == user_id,
        )
    )
    
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Query not found for the given query id")
    
    status=record.status
    return status

# ------------ business logic functions -------------
async def raise_validate_query(body: ValidateQueryInput, db: AsyncSession, current_user: User) -> dict:
    result = await db.execute(
        select(Onboarding).where(Onboarding.user_id == current_user.id)
    )
    onboarding = result.scalar_one_or_none()
    
    profile = {}
    if onboarding:
        profile = {
            "occupation": onboarding.occupation,
            "discovery":  onboarding.discovery,
            "usage":      onboarding.usage,
        }
    
    # Add the location data to the profile so it can be used later
    if body.location:
        profile["location"] = body.location

    record = ValidateQuery(
        user_id=              current_user.id,
        user_email=           current_user.email,
        title=                body.title,
        description=          body.description,
        industry=             body.industry,
        stage=                body.stage,
        profile=              profile,
        status=               ValidateQueryStatus.INITIALIZED,
    )
    db.add(record)
    await db.flush()

    try:
        record.start_step(ValidateQueryStatus.CREATED)
        await db.commit()
        
    except Exception as e:
        logger.error(f"Failed to process validate query {record.id}: {e}")
        record.fail_step(str(e))
        await db.commit()
        return {
            "id":             str(record.id),
            "status":         record.status,
            "failure_reason": record.failure_reason,
            "failed_at_step": record.failed_at_step,
        }

    return {
        "id":     str(record.id),
        "status": record.status,
    }

async def generate_context(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.CREATED:
        raise HTTPException(
            status_code=400,
            detail=f"Query must be created before generating context, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="validate", mode="generate-context")
    record.runpod_job_id = job_id
    # record.start_step(ValidateQueryStatus.VALIDATING)
    await db.commit()
    logger.info("Context generation triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": "VALIDATING", "runpod_job_id": job_id}

async def trigger_search(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.VALIDATED:
        raise HTTPException(
            status_code=400,
            detail=f"Context must be generated before searching, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="validate", mode="search")
    record.runpod_job_id = job_id
    # record.start_step(ValidateQueryStatus.SEARCHING)
    await db.commit()
    logger.info("Search triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": "SEARCHING", "runpod_job_id": job_id}

async def trigger_filter(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.SEARCH_COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Search must be generated before filtering, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="validate", mode="filter")
    record.runpod_job_id = job_id
    # record.start_step(ValidateQueryStatus.SEARCHING)
    await db.commit()
    logger.info("Filter triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": "FILTERING", "runpod_job_id": job_id}

async def trigger_extract(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.FILTERED:
        raise HTTPException(
            status_code=400,
            detail=f"Filtering must be completed before extraction, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="validate", mode="extract")
    record.runpod_job_id = job_id
    # record.start_step(ValidateQueryStatus.SEARCHING)
    await db.commit()
    logger.info("Filter triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": "EXTRACTING", "runpod_job_id": job_id}

async def trigger_score(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.EXTRACTED:
        raise HTTPException(
            status_code=400,
            detail=f"Extraction must be completed before scoring, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="validate", mode="score")
    record.runpod_job_id = job_id
    # record.start_step(ValidateQueryStatus.SEARCHING)
    await db.commit()
    logger.info("Score triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": "SCORING", "runpod_job_id": job_id}

async def generate_summary(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.SCORED:
        raise HTTPException(
            status_code=400,
            detail=f"Scoring must be completed before generating summary, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="validate", mode="summary")
    record.runpod_job_id = job_id
    # record.start_step(ValidateQueryStatus.SCORING)
    await db.commit()
    logger.info("Summary generation triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": "SUMMARIZING", "runpod_job_id": job_id}

async def get_summary(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    # 1. Validate ownership and ensure the pipeline is completely finished
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Summary generation must be completed before fetching, current: {record.status}",
        )

    # 2. Load the stored report. The row is locked so two simultaneous
    #    first fetches cannot both charge or both unlock.
    result = await db.execute(
        select(ValidateQueryResult)
        .where(ValidateQueryResult.query_id == query_id)
        .with_for_update()
    )
    summary_record = result.scalars().first()
    stored = summary_record.report if summary_record else None

    if not stored:
        raise HTTPException(
            status_code=404,
            detail="Summary not found for this query even though status is COMPLETED. "
                   "The pipeline may have failed during the final database save.",
        )

    report_data = copy.deepcopy(stored)   # work on a copy; the stored report keeps the full data

    # 3. First fetch only: unlock sections by credits, deduct, bump fetch
    if report_data.get("fetch") == 1:
        user_row = (
            await db.execute(
                select(User)
                .where(User.id == current_user.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars().one()

        credits = user_row.credits or 0
        params = report_data.get("parameters") or {}
        all_keys = list(params.keys())

        allowed_count = min(credits // SECTION_CREDITS, len(all_keys))
        ordered = [k for k in PRIORITY_KEYS if k in params] + \
                  [k for k in all_keys if k not in PRIORITY_KEYS]
        unlocked = ordered[:allowed_count]

        for key in unlocked:
            params[key]["locked"] = False          # every other section stays locked: True

        new_credits = credits - len(unlocked) * SECTION_CREDITS
        user_row.credits = new_credits
        report_data["fetch"] += 1                  # 1 -> 2, so this never charges again
        summary_record.report = report_data        # new object, so SQLAlchemy sees the change

        await db.commit()                          # report + credits in one transaction
        current_user.credits = new_credits         # keep the request's user object in sync

    # 4. Build the response: locked sections are masked in the copy only and exists in db
    response = copy.deepcopy(report_data)
    for key, block in (response.get("parameters") or {}).items():
        if isinstance(block, dict) and block.get("locked", False):
            response["parameters"][key] = {"locked": True}

    return response

async def get_queries(
    user_id: str, 
    db: AsyncSession, 
    page: int = 1, 
    page_size: int = 10
) -> Dict[str, Any]:
    """
    Fetches paginated validation queries for a specific user, ordered by the newest first.
    """
    # 1. Calculate the offset based on the requested page
    offset = (page - 1) * page_size

    # 2. Query for the total count of records (essential for frontend pagination controls)
    count_query = select(func.count()).select_from(ValidateQuery).where(ValidateQuery.user_id == user_id)
    total_result = await db.execute(count_query)
    total_count = total_result.scalar() or 0

    # 3. Execute the paginated query
    result = await db.execute(
        select(ValidateQuery)
        .where(ValidateQuery.user_id == user_id)
        .order_by(ValidateQuery.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    
    # 4. Extract all records for the current page
    records = result.scalars().all()

    # 5. Serialize the data
    items = [
        {
            "id": str(record.id),
            "title": record.title,
            "status": record.status,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
        for record in records
    ]

    # 6. Return a structured dictionary containing the items and pagination metadata
    return {
        "items": items,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total_count / page_size) if total_count > 0 else 1
    }
    
async def process_section_unlock(query_id: UUID, section_name: str, db: AsyncSession, current_user: User) -> dict:
    # 1. Fetch and lock the report to prevent race conditions
    result = await db.execute(
        select(ValidateQueryResult)
        .where(ValidateQueryResult.query_id == query_id)
        .with_for_update()
    )
    summary_record = result.scalars().first()
    
    if not summary_record or not summary_record.report:
        raise HTTPException(status_code=404, detail="Report not found.")
        
    report_data = copy.deepcopy(summary_record.report)
    params = report_data.get("parameters", {})
    
    # 2. Check if the requested section exists and is actually locked
    if section_name not in params:
        raise HTTPException(status_code=404, detail=f"Section '{section_name}' does not exist.")
        
    if not params[section_name].get("locked", False):
        raise HTTPException(status_code=400, detail=f"Section '{section_name}' is already unlocked.")
    
    # 3. Lock the user row to safely read and deduct credits
    user_row = (
        await db.execute(
            select(User).where(User.id == current_user.id).with_for_update()
        )
    ).scalars().one()

    # 4. Check if there are enough credits
    credits = user_row.credits or 0
    if credits < SECTION_CREDITS:
        raise HTTPException(status_code=400, detail="Not enough credits to unlock this section.")

    # 5. Unlock the specific section in the JSON document
    params[section_name]["locked"] = False

    # 6. Deduct the exact credit cost and save to DB
    new_credits = credits - SECTION_CREDITS
    user_row.credits = new_credits
    
    # SQLAlchemy requires assigning a new dictionary object to detect JSON changes
    summary_record.report = report_data 
    
    await db.commit()

    return {
        "status": "success",
        "unlocked_section": section_name,
        "remaining_credits": new_credits
    }