import logging
import math
from uuid import UUID
from typing import List, Dict, Any
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.validate.model import ValidateQuery, ValidateQueryStatus, ValidateScoreSummary, ValidateQueryResult
from src.app.onboarding.model import Onboarding
from src.app.user.model import User
from src.app.validate.schema import ValidateQueryInput
from src.infra.runpod.client import trigger as runpod_trigger

logger = logging.getLogger(__name__)

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

    # 2. Fetch the actual summary data from the ValidateScoreSummary table
    result = await db.execute(
        select(ValidateQueryResult).where(ValidateQueryResult.query_id == query_id)
    )
    summary_record = result.scalars().first()

    # Access the report JSONB column
    report_data = summary_record.report if summary_record else None
    
    if not report_data:
        raise HTTPException(
            status_code=404,
            detail="Summary not found for this query even though status is COMPLETED. The pipeline may have failed during the final database save."
        )
    
    return report_data

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