import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.validate.model import ValidateQuery, ValidateQueryStatus
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
    record.start_step(ValidateQueryStatus.VALIDATING)
    await db.commit()
    logger.info("Context generation triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": record.status, "runpod_job_id": job_id}

async def trigger_search(query_id: UUID, db: AsyncSession, current_user: User) -> dict:
    record = await _get_query_or_404(query_id, current_user.id, db)

    if record.status != ValidateQueryStatus.VALIDATED:
        raise HTTPException(
            status_code=400,
            detail=f"Context must be generated before searching, current: {record.status}",
        )

    job_id = await runpod_trigger(str(query_id), service="validate", mode="search")
    record.runpod_job_id = job_id
    record.start_step(ValidateQueryStatus.SEARCHING)
    await db.commit()
    logger.info("Search triggered", extra={"query_id": str(query_id), "job_id": job_id})
    return {"id": str(record.id), "status": record.status, "runpod_job_id": job_id}

