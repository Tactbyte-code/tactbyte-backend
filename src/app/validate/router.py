from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from src.core.database import session
from src.app.middleware.auth import require_user
from src.app.user.model import User
from src.app.validate.schema import ValidateQueryInput
from src.app.validate import services

router = APIRouter(prefix="/validate", tags=["Validate Idea"])

# ------- query creation -------
@router.post("/query", status_code=201)
async def raise_validate_query(
    body: ValidateQueryInput,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.raise_validate_query(body, db, current_user)

# ------- context generation -------
@router.post("/query/{query_id}/generate-context")
async def generate_context(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.generate_context(query_id, db, current_user)

# ------- search triggering -------
@router.post("/query/{query_id}/search")
async def trigger_search(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.trigger_search(query_id, db, current_user)

# ------- get status -------
@router.get("/query/{query_id}/status")
async def get_status(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.get_status(query_id, current_user.id, db)