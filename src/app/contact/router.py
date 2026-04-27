from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from src.core.database import session
from src.app.contact.model import Contact
from src.app.contact.schema import ContactCreate, ContactResponse
from src.app.middleware.auth import require_user
from src.app.user.model import User
from sqlalchemy import select
router = APIRouter()

@router.post("/contact", response_model=ContactResponse)
async def submit_contact(
    feedback: ContactCreate,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user)
):
    db_contact = Contact(
        user_id=current_user.id,
        full_name=current_user.full_name,
        email=current_user.email,
        phone=feedback.phone,
        message=feedback.message
    )

    db.add(db_contact)

    await db.commit()            
    await db.refresh(db_contact)

    return db_contact

@router.get("/contact", response_model=list[ContactResponse])
async def get_all_contact(db: AsyncSession = Depends(session)):
    result = await db.execute(
        select(Contact).order_by(Contact.created_at.desc())
    )
    return result.scalars().all()