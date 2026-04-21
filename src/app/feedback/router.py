from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from src.core.database import session
from src.app.feedback.model import Feedback
from src.app.feedback.schema import FeedbackCreate, FeedbackResponse
from src.app.middleware.auth import require_user
from src.app.user.model import User
from sqlalchemy import select
router = APIRouter()

@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    feedback: FeedbackCreate,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user)
):
    db_feedback = Feedback(
        user_id=current_user.id,
        full_name=current_user.full_name,
        email=current_user.email,
        phone=feedback.phone,
        message=feedback.message
    )

    db.add(db_feedback)

    await db.commit()            # ✅ FIX
    await db.refresh(db_feedback) # ✅ FIX

    return db_feedback

@router.get("/feedback", response_model=list[FeedbackResponse])
async def get_all_feedback(db: AsyncSession = Depends(session)):
    result = await db.execute(
        select(Feedback).order_by(Feedback.created_at.desc())
    )
    return result.scalars().all()