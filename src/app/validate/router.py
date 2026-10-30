from fastapi import APIRouter, Depends, Query, HTTPException
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



# @router.post("/deduct", status_code=200)
# async def deduct_report_credits(
#     body: DeductCreditsInput,
#     db: AsyncSession = Depends(session),
#     current_user: User = Depends(require_user),
# ):
#     per_section_credits = 22
#     cost = body.sections_unlocked * per_section_credits
#     balance = current_user.credits or 0

#     if balance < cost:
#         raise HTTPException(
#             status_code=400,
#             detail=f"Insufficient balance. Need {cost} credits, but you have {balance}.",
#         )

#     current_user.credits = balance - cost
#     db.add(current_user)
#     await db.commit()
#     await db.refresh(current_user)

#     return {
#         "success": True,
#         "deducted": cost,
#         "remaining_credits": current_user.credits,
#         "sections_unlocked": body.sections_unlocked,
#     }




# ------- get status -------
@router.get("/query/{query_id}/status")
async def get_status(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.get_status(query_id, current_user.id, db)

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

# ------- filter data -------
@router.post("/query/{query_id}/filter")
async def trigger_filter(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.trigger_filter(query_id, db, current_user)

# ------- extract data -------
@router.post("/query/{query_id}/extract")
async def trigger_extract(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.trigger_extract(query_id, db, current_user)

# ------- score data -------
@router.post("/query/{query_id}/score")
async def trigger_score(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.trigger_score(query_id, db, current_user)

# ------- generate summary -------
@router.post("/query/{query_id}/generate-summary")
async def generate_summary(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.generate_summary(query_id, db, current_user)

# ------- get summary -------
@router.get("/query/{query_id}/summary")
async def get_summary(
    query_id: UUID,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await services.get_summary(query_id, db, current_user)

# ------- get queries -------
@router.get("/query")
async def get_queries(
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page")
):
    # Pass the pagination parameters to your service function
    return await services.get_queries(
        user_id=current_user.id, 
        db=db, 
        page=page, 
        page_size=page_size
    )

