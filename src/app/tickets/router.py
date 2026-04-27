import asyncio
from functools import partial
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime

from src.core.database import session
from src.app.middleware.auth import require_admin

from src.app.tickets import models, schemas
from src.app.tickets.models import PLAN_PRIORITY_MAP, TYPE_TEAM_MAP, UserPlan, TicketType
from src.app.teams.models import Team

# ✅ FIXED: was "ticket_close_email" (wrong name → "the first argument must be callable")
from src.app.utils.ticket_close_email import send_ticket_closed_email

router = APIRouter(prefix="/tickets", tags=["Tickets"])


# ── Helper: always eager-load replies ─────────────────────────────────────────
def _ticket_query():
    return select(models.Ticket).options(selectinload(models.Ticket.replies))


async def get_team_by_slug(db: AsyncSession, slug: str):
    result = await db.execute(select(Team).where(Team.slug == slug))
    return result.scalar_one_or_none()


async def _send_closed_email_bg(ticket: models.Ticket, team_name: str):
    """Fire-and-forget: run blocking SMTP in a thread-pool so the route returns fast."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            partial(
                send_ticket_closed_email,          # ✅ correct callable
                ticket.user_email,
                ticket.user_name or ticket.user_email.split("@")[0],
                ticket.ticket_id or f"TIK{ticket.id:03d}",
                ticket.subject or "your recent inquiry",
                team_name,
            ),
        )
    except Exception as exc:
        print(f"⚠️  Could not send closure email for ticket {ticket.id}: {exc}")


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
    query = _ticket_query()

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
        _ticket_query().where(models.Ticket.id == ticket_id)
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
        raise HTTPException(status_code=400, detail=f"Team '{team_slug}' not found in DB")

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


# ── PATCH /tickets/{ticket_id}/status ─────────────────────────────────────────
@router.patch("/{ticket_id}/status", response_model=schemas.TicketOut)
async def update_status(
    ticket_id: int,
    body: schemas.TicketStatusUpdate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    previous_status = ticket.status
    ticket.status = body.status
    ticket.updated_at = datetime.utcnow()
    await db.commit()

    # ── Send closure email when status transitions → closed ──────────────────
    if body.status == "closed" and previous_status != "closed":
        team_obj  = await get_team_by_slug(db, ticket.assigned_team)
        team_name = team_obj.name if team_obj else ticket.assigned_team.capitalize()
        asyncio.create_task(_send_closed_email_bg(ticket, team_name))

    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)
    )
    return result.scalar_one()


# ── PATCH /tickets/{ticket_id}/priority ───────────────────────────────────────
@router.patch("/{ticket_id}/priority", response_model=schemas.TicketOut)
async def update_priority(
    ticket_id: int,
    body: schemas.TicketPriorityUpdate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.priority = body.priority
    ticket.updated_at = datetime.utcnow()
    await db.commit()

    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)
    )
    return result.scalar_one()


# ── POST /tickets/{ticket_id}/reply ───────────────────────────────────────────
@router.post("/{ticket_id}/reply", response_model=schemas.TicketOut)
async def reply_to_ticket(
    ticket_id: int,
    body: schemas.ReplyCreate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)
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

    result = await db.execute(
        _ticket_query().where(models.Ticket.id == ticket_id)
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
        _ticket_query().where(models.Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    target_team = await get_team_by_slug(db, body.to_team)
    if not target_team:
        raise HTTPException(status_code=400, detail=f"Invalid team: {body.to_team}")
    if body.to_team == ticket.assigned_team:
        raise HTTPException(status_code=400, detail="Already assigned to this team")

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
        _ticket_query().where(models.Ticket.id == ticket_id)
    )
    return result.scalar_one()