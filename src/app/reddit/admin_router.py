from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import session
from src.app.middleware.auth import require_user, require_admin
from src.app.reddit import services

router = APIRouter(prefix="/reddit", tags=["Reddit"])

@router.get("/queries")
async def get_queries(
    db: AsyncSession = Depends(session),
    current_user = Depends(require_admin),
):
    return await services.get_all_query(db)