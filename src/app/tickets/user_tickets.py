"""
src/app/tickets/user_router.py

Key optimisations vs previous version
──────────────────────────────────────
Same _commit_and_broadcast pattern as the admin router:
every mutation commits once, fetches once, broadcasts once.
"""

import asyncio
import json
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.app.middleware.auth import require_user
from src.app.teams.models import Team
from src.app.tickets import models, schemas
from src.app.tickets.models import PLAN_PRIORITY_MAP, TYPE_TEAM_MAP, TicketType, UserPlan
from src.app.tickets.sse_manager import sse_manager
from src.app.user.model import User
from src.core.database import session

router = APIRouter(prefix="/user/tickets", tags=["User Tickets"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ticket_query():
    return select(models.Ticket).options(selectinload(models.Ticket.replies))


async def get_team_by_slug(db: AsyncSession, slug: str):
    result = await db.execute(select(Team).where(Team.slug == slug))
    return result.scalar_one_or_none()


async def _commit_and_broadcast(db: AsyncSession, ticket_id: int) -> models.Ticket:
    """
    Commit, fetch once, broadcast to SSE subscribers, return the ticket.
    Callers get one round-trip instead of two.
    """
    await db.commit()

    result = await db.execute(_ticket_query().where(models.Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if sse_manager.has_subscribers(ticket_id):
        payload = {
            "type": "ticket_update",
            "ticket": schemas.TicketOut.model_validate(ticket).model_dump(mode="json"),
        }
        await sse_manager.broadcast(ticket_id, payload)

    return ticket


# ── GET /user/tickets/ ────────────────────────────────────────────────────────

@router.get("/", response_model=List[schemas.TicketOut])
async def get_user_tickets(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(session),
):
    result = await db.execute(
        _ticket_query()
        .where(models.Ticket.user_email == user.email)
        .order_by(models.Ticket.created_at.desc())
    )
    return result.scalars().all()


# ── GET /user/tickets/{ticket_id} ─────────────────────────────────────────────

@router.get("/{ticket_id}", response_model=schemas.TicketOut)
async def get_user_ticket(
    ticket_id: int,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(session),
):
    result = await db.execute(
        _ticket_query()
        .where(models.Ticket.id == ticket_id)
        .where(models.Ticket.user_email == user.email)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# ── GET /user/tickets/{ticket_id}/stream  (SSE) ────────────────────────────────

@router.get("/{ticket_id}/stream")
async def user_ticket_stream(
    ticket_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(session),
):
    """
    SSE stream — user side. Uses fetch + ReadableStream so the Firebase
    Authorization header is forwarded correctly.

    Events:
      {"type": "init",          "ticket": <TicketOut>}  — on connect
      {"type": "ticket_update", "ticket": <TicketOut>}  — on any mutation
      {"type": "heartbeat"}                             — every 15 s
    """
    result = await db.execute(
        _ticket_query()
        .where(models.Ticket.id == ticket_id)
        .where(models.Ticket.user_email == user.email)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    init_payload = json.dumps({
        "type": "init",
        "ticket": schemas.TicketOut.model_validate(ticket).model_dump(mode="json"),
    })

    queue = sse_manager.subscribe(ticket_id)

    async def generator():
        yield f"data: {init_payload}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type":"heartbeat"}\n\n'
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.unsubscribe(ticket_id, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


# ── POST /user/tickets/ ───────────────────────────────────────────────────────

@router.post("/", response_model=schemas.TicketOut)
async def create_user_ticket(
    body: schemas.TicketCreate,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(session),
):
    data = body.model_dump()
    data["user_email"] = user.email
    data["user_name"] = user.full_name or user.email.split("@")[0]

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

    return await _commit_and_broadcast(db, ticket.id)


# ── POST /user/tickets/{ticket_id}/reply ─────────────────────────────────────

@router.post("/{ticket_id}/reply", response_model=schemas.TicketOut)
async def user_reply_to_ticket(
    ticket_id: int,
    body: schemas.ReplyCreate,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(session),
):
    result = await db.execute(
        _ticket_query()
        .where(models.Ticket.id == ticket_id)
        .where(models.Ticket.user_email == user.email)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    reply = models.TicketReply(
        ticket_id=ticket_id,
        message=body.message,
        is_admin=0,
        reply_type="message",
    )
    db.add(reply)
    ticket.updated_at = datetime.utcnow()

    return await _commit_and_broadcast(db, ticket_id)


# ── GET /user/tickets/teams/active ───────────────────────────────────────────

@router.get("/teams/active")
async def get_active_teams(db: AsyncSession = Depends(session)):
    """Public endpoint — no auth required."""
    result = await db.execute(
        select(Team).where(Team.is_active == True).order_by(Team.name)
    )
    teams = result.scalars().all()
    return [
        {"id": t.id, "name": t.name, "slug": t.slug, "color": t.color, "icon": t.icon}
        for t in teams
    ]