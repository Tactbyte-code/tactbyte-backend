from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime

from src.core.database import session
from src.app.tickets import models, schemas
from src.app.tickets.models import PLAN_PRIORITY_MAP, TYPE_TEAM_MAP, UserPlan, TicketType
from src.app.teams.models import Team

router = APIRouter(prefix="/user/tickets", tags=["User Tickets"])


def _ticket_query():
    return select(models.Ticket).options(selectinload(models.Ticket.replies))


async def get_team_by_slug(db: AsyncSession, slug: str):
    result = await db.execute(select(Team).where(Team.slug == slug))
    return result.scalar_one_or_none()


# ── GET /user/tickets/?email=... ──────────────────────────────────────────────
@router.get("/", response_model=List[schemas.TicketOut])
async def get_user_tickets(
    email: str = Query(...),
    db: AsyncSession = Depends(session),
):
    """Return all tickets belonging to the given email, newest first."""
    result = await db.execute(
        _ticket_query()
        .where(models.Ticket.user_email == email)
        .order_by(models.Ticket.created_at.desc())
    )
    return result.scalars().all()


# ── GET /user/tickets/{ticket_id}?email=... ───────────────────────────────────
@router.get("/{ticket_id}", response_model=schemas.TicketOut)
async def get_user_ticket(
    ticket_id: int,
    email: str = Query(...),
    db: AsyncSession = Depends(session),
):
    result = await db.execute(
        _ticket_query()
        .where(models.Ticket.id == ticket_id)
        .where(models.Ticket.user_email == email)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# ── POST /user/tickets/ ───────────────────────────────────────────────────────
@router.post("/", response_model=schemas.TicketOut)
async def create_user_ticket(
    body: schemas.TicketCreate,
    db: AsyncSession = Depends(session),
):
    data = body.model_dump()

    try:
        user_plan = UserPlan(data.get("user_plan", "free"))
    except ValueError:
        user_plan = UserPlan.free

    data["priority"] = PLAN_PRIORITY_MAP.get(user_plan, models.TicketPriority.low).value
    data["user_plan"] = user_plan.value

    try:
        ticket_type = TicketType(data.get("ticket_type", "other"))
    except ValueError:
        ticket_type = TicketType.other

    team_slug = TYPE_TEAM_MAP.get(ticket_type, "general")
    team = await get_team_by_slug(db, team_slug)
    if not team:
        raise HTTPException(status_code=400, detail=f"Team '{team_slug}' not found")

    data["assigned_team"] = team.slug
    data["ticket_type"] = ticket_type.value

    ticket = models.Ticket(**data)
    db.add(ticket)
    await db.flush()
    ticket.ticket_id = f"TIK{ticket.id:03d}"
    await db.commit()

    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket.id)
    )
    return result.scalar_one()


# ── POST /user/tickets/{ticket_id}/reply ─────────────────────────────────────
@router.post("/{ticket_id}/reply", response_model=schemas.TicketOut)
async def user_reply_to_ticket(
    ticket_id: int,
    body: schemas.ReplyCreate,
    email: str = Query(...),
    db: AsyncSession = Depends(session),
):
    """Allow the ticket owner (verified by email) to reply."""
    result = await db.execute(
        _ticket_query()
        .where(models.Ticket.id == ticket_id)
        .where(models.Ticket.user_email == email)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    reply = models.TicketReply(
        ticket_id=ticket_id,
        message=body.message,
        is_admin=0,          # ← user reply
        reply_type="message",
    )
    db.add(reply)
    ticket.updated_at = datetime.utcnow()
    await db.commit()

    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)
    )
    return result.scalar_one()


# ── GET /user/tickets/teams/active ───────────────────────────────────────────
@router.get("/teams/active")
async def get_active_teams(db: AsyncSession = Depends(session)):
    """Public endpoint — returns active support teams for the new-ticket dropdown."""
    result = await db.execute(
        select(Team).where(Team.is_active == True).order_by(Team.name)
    )
    teams = result.scalars().all()
    return [{"id": t.id, "name": t.name, "slug": t.slug, "color": t.color, "icon": t.icon} for t in teams]