from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.database import session
from src.app.feedback.model import Feedback
from src.app.feedback.schema import FeedbackCreate, FeedbackResponse
from src.app.middleware.auth import require_user
from src.app.user.model import User

router = APIRouter()

@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    feedback: FeedbackCreate,
    db: AsyncSession = Depends(session),
):
    if not (0 <= feedback.score <= 10):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Score must be between 0 and 10"
        )

    if not feedback.selected_features:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one feature must be selected"
        )

    db_feedback = Feedback(
        email=feedback.email,
        score=feedback.score,
        selected_features=feedback.selected_features,
        comments=feedback.comments,
    )

    db.add(db_feedback)
    await db.commit()
    await db.refresh(db_feedback)

    return db_feedback


@router.get("/feedback", response_model=list[FeedbackResponse])
async def get_all_feedback(
    db: AsyncSession = Depends(session),
):
    result = await db.execute(
        select(Feedback).order_by(Feedback.created_at.desc())
    )
    return result.scalars().all()