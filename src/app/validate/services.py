import logging
from uuid import UUID
from typing import List, Dict, Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.validate.model import ValidateQuery, ValidateQueryStatus, ValidateScoreSummary, ValidateMarketSource
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
    
    profile = body.profile or {}
    if onboarding:
        profile = {
            "occupation": onboarding.occupation,
            "discovery":  onboarding.discovery,
            "usage":      onboarding.usage,
            **profile,
        }

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

async def generate_summary(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.SEARCH_COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Search must be completed before generating summary, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="validate", mode="summary")
    record.runpod_job_id = job_id
    # record.start_step(ValidateQueryStatus.SCORING)
    await db.commit()
    logger.info("Summary generation triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": "SCORING", "runpod_job_id": job_id}

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
        select(ValidateScoreSummary).where(ValidateScoreSummary.query_id == query_id)
    )
    summary_record = result.scalars().first()

    if not summary_record:
        raise HTTPException(
            status_code=404,
            detail="Score summary not found for this query even though status is COMPLETED. The pipeline may have failed during the final database save."
        )
    
    # 3. Dynamically fetch the approved sources directly from the database
    # sources_result = await db.execute(
    #     select(ValidateMarketSource)
    #     .where(ValidateMarketSource.query_id == query_id)
    #     .where(ValidateMarketSource.user_approved.is_(True))
    # )
    # sources = sources_result.scalars().all()

    # # Format the sources exactly as the UI expects them
    # all_sources_data = [
    #     {"title": src.title, "url": src.url, "snippet": src.snippet} 
    #     for src in sources
    # ]

    # 4. Return the fully structured UI deliverables
    return {
        "id": str(summary_record.id),
        "query_id": str(summary_record.query_id),
        # Base Venture Details (From ValidateQuery)
        "title": record.title,
        "description": record.description,
        "industry": record.industry,
        "stage": record.stage,
        "executive_verdict": summary_record.executive_verdict,
        "aggregate_score": summary_record.aggregate_score,
        "dimensional_scores": summary_record.dimensional_scores or {},
        "competitive_landscape": summary_record.competitive_landscape or [],
        "critical_vulnerabilities": summary_record.critical_vulnerabilities or [],
        "actionable_next_steps": summary_record.actionable_next_steps or [],
        "evidentiary_sources": summary_record.evidentiary_sources or [],
        # "all_sources": all_sources_data,
        "meta": summary_record.meta or {},
        "created_at": summary_record.created_at.isoformat() if summary_record.created_at else None,
        "updated_at": summary_record.updated_at.isoformat() if summary_record.updated_at else None,
    }

async def get_queries(user_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Fetches all validation queries for a specific user, ordered by the newest first.
    """
    # 1. Execute the query
    result = await db.execute(
        select(ValidateQuery)
        .where(ValidateQuery.user_id == user_id)
        .order_by(ValidateQuery.created_at.desc())
    )
    
    # 2. Extract all records
    records = result.scalars().all()

    # 3. Serialize and return as a list of dictionaries for the FastAPI JSON response
    return [
        {
            "id": str(record.id),
            "title": record.title,
            "status": record.status,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
        for record in records
    ]