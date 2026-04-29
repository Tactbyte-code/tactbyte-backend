# src/app/ai_lead_engine/action_service.py

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from src.app.ai_lead_engine.model import LeadAction
from src.app.ai_lead_engine.schema import CreateLeadActionBody
from src.app.user.model import User


async def get_actions(db: AsyncSession, user: User, lead_id: str) -> list[LeadAction]:
    result = await db.execute(
        select(LeadAction)
        .where(LeadAction.lead_id == UUID(lead_id))
        .order_by(LeadAction.created_at.desc())
    )
    return result.scalars().all()


async def create_action(
    db: AsyncSession,
    user: User,
    lead_id: str,
    body: CreateLeadActionBody,
) -> LeadAction:
    valid_types = {"replied", "ignored", "bookmarked", "converted"}
    if body.action_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid action_type. Must be one of: {valid_types}",
        )

    action = LeadAction(
        lead_id=UUID(lead_id),
        action_type=body.action_type,
        note=body.note,
        reply_text=body.reply_text,
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return action


async def delete_action(db: AsyncSession, user: User, action_id: str) -> None:
    result = await db.execute(
        select(LeadAction).where(LeadAction.id == UUID(action_id))
    )
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")

    await db.delete(action)
    await db.commit()