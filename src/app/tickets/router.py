from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload          # ← FIX: needed for async eager-load
from typing import List, Optional
from datetime import datetime

from src.core.database import session
from src.app.middleware.auth import require_admin

from src.app.tickets import models, schemas
from src.app.tickets.models import PLAN_PRIORITY_MAP, TYPE_TEAM_MAP, UserPlan, TicketType
from src.app.teams.models import Team

router = APIRouter(prefix="/tickets", tags=["Tickets"])


# ── Helper: always eager-load replies so async session never lazy-loads ────────
def _ticket_query():
    """Base select that pre-loads the replies relationship.

    AsyncSession does NOT support implicit lazy loading. Any query returning a
    Ticket that will be serialised via TicketOut (which includes
    replies: List[TicketReplyOut]) must use selectinload, otherwise SQLAlchemy
    raises MissingGreenlet → 500 Internal Server Error.
    """
    return select(models.Ticket).options(selectinload(models.Ticket.replies))


async def get_team_by_slug(db: AsyncSession, slug: str):
    result = await db.execute(select(Team).where(Team.slug == slug))
    return result.scalar_one_or_none()


# ── GET /tickets/ ──────────────────────────────────────────────────────────────
@router.get("/", response_model=List[schemas.TicketOut])
async def get_tickets(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    ticket_type: Optional[str] = Query(None),
    assigned_team: Optional[str] = Query(None),
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    query = _ticket_query()                      # ← eager-load replies

    if status:
        query = query.where(models.Ticket.status == status)
    if priority:
        query = query.where(models.Ticket.priority == priority)
    if ticket_type:
        query = query.where(models.Ticket.ticket_type == ticket_type)
    if assigned_team:
        query = query.where(models.Ticket.assigned_team == assigned_team)

    result = await db.execute(query.order_by(models.Ticket.created_at.desc()))
    return result.scalars().all()


# ── GET /tickets/{ticket_id} ───────────────────────────────────────────────────
@router.get("/{ticket_id}", response_model=schemas.TicketOut)
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)   # ← eager-load replies
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return ticket


# ── POST /tickets/ ─────────────────────────────────────────────────────────────
@router.post("/", response_model=schemas.TicketOut)
async def create_ticket(
    body: schemas.TicketCreate,
    db: AsyncSession = Depends(session),
):
    data = body.model_dump()

    # Priority from plan
    try:
        user_plan = UserPlan(data.get("user_plan", "free"))
    except ValueError:
        user_plan = UserPlan.free

    data["priority"] = PLAN_PRIORITY_MAP.get(user_plan, models.TicketPriority.low).value
    data["user_plan"] = user_plan.value

    # Team from type → validate against DB
    try:
        ticket_type = TicketType(data.get("ticket_type", "other"))
    except ValueError:
        ticket_type = TicketType.other

    team_slug = TYPE_TEAM_MAP.get(ticket_type, "general")

    team = await get_team_by_slug(db, team_slug)
    if not team:
        raise HTTPException(status_code=400, detail=f"Team '{team_slug}' not found in DB")

    data["assigned_team"] = team.slug
    data["ticket_type"] = ticket_type.value

    ticket = models.Ticket(**data)
    db.add(ticket)

    await db.flush()
    ticket.ticket_id = f"TIK{ticket.id:03d}"

    await db.commit()

    # Re-fetch with eager-loaded replies instead of relying on db.refresh,
    # which would still lazy-load the relationship on an async session.
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket.id)   # ← eager-load replies
    )
    return result.scalar_one()


# ── PATCH /tickets/{ticket_id}/status ─────────────────────────────────────────
@router.patch("/{ticket_id}/status", response_model=schemas.TicketOut)
async def update_status(
    ticket_id: int,
    body: schemas.TicketStatusUpdate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)   # ← eager-load replies
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.status = body.status
    ticket.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(ticket)

    return ticket


# ── PATCH /tickets/{ticket_id}/priority ───────────────────────────────────────
@router.patch("/{ticket_id}/priority", response_model=schemas.TicketOut)
async def update_priority(
    ticket_id: int,
    body: schemas.TicketPriorityUpdate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)   # ← eager-load replies
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.priority = body.priority
    ticket.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(ticket)

    return ticket


# ── POST /tickets/{ticket_id}/reply ───────────────────────────────────────────
@router.post("/{ticket_id}/reply", response_model=schemas.TicketOut)
async def reply_to_ticket(
    ticket_id: int,
    body: schemas.ReplyCreate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)   # ← eager-load replies
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    reply = models.TicketReply(
        ticket_id=ticket_id,
        message=body.message,
        is_admin=1,
        reply_type="message",
    )
    db.add(reply)

    if ticket.status == models.TicketStatus.open:
        ticket.status = models.TicketStatus.in_progress

    ticket.updated_at = datetime.utcnow()

    await db.commit()

    # Re-fetch so the new reply is included in the returned replies list.
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)   # ← fresh eager-load
    )
    return result.scalar_one()


# ── POST /tickets/{ticket_id}/forward ─────────────────────────────────────────
@router.post("/{ticket_id}/forward", response_model=schemas.TicketOut)
async def forward_ticket(
    ticket_id: int,
    body: schemas.ForwardTicket,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)   # ← eager-load replies
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    target_team = await get_team_by_slug(db, body.to_team)
    if not target_team:
        raise HTTPException(status_code=400, detail=f"Invalid team: {body.to_team}")

    if body.to_team == ticket.assigned_team:
        raise HTTPException(status_code=400, detail="Already assigned")

    note_part = f"\n\nNote: {body.note}" if body.note else ""

    reply = models.TicketReply(
        ticket_id=ticket_id,
        message=f"Forwarded to {target_team.name}.{note_part}",
        is_admin=1,
        reply_type="forwarded",
        forwarded_from_team=ticket.assigned_team,
        forwarded_to_team=body.to_team,
    )
    db.add(reply)

    ticket.assigned_team = body.to_team
    ticket.updated_at = datetime.utcnow()

    if ticket.status == models.TicketStatus.open:
        ticket.status = models.TicketStatus.in_progress

    await db.commit()


    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)   # ← fresh eager-load
    )
    return result.scalar_one()