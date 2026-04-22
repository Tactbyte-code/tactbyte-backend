from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from src.core.database import session
from src.app.middleware.auth import require_user, require_admin
from fastapi.exceptions import HTTPException

from src.app.teams.models import Team
from src.app.teams import schemas

router = APIRouter(prefix="/teams", tags=["Teams"])

@router.get("/")
async def get_teams(
    db: AsyncSession = Depends(session),
    current_admin = Depends(require_admin),
):
    result = await db.execute(select(Team).order_by(Team.name))
    return result.scalars().all()

@router.get("/{team_id}")
async def get_team(
    team_id: int,
    db: AsyncSession = Depends(session),
    current_admin = Depends(require_admin),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    return team

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_team(
    body: schemas.TeamCreate,
    db: AsyncSession = Depends(session),
    current_admin = Depends(require_admin),
):
    # Check slug uniqueness
    result = await db.execute(select(Team).where(Team.slug == body.slug))
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug already in use",
        )

    team = Team(**body.model_dump())

    db.add(team)
    await db.commit()
    await db.refresh(team)

    return team

@router.patch("/{team_id}")
async def update_team(
    team_id: int,
    body: schemas.TeamUpdate,
    db: AsyncSession = Depends(session),
    current_admin = Depends(require_admin),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    data = body.model_dump(exclude_unset=True)

    if "slug" in data and data["slug"] != team.slug:
        result = await db.execute(select(Team).where(Team.slug == data["slug"]))
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slug already in use",
            )

    for key, value in data.items():
        setattr(team, key, value)

    team.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(team)

    return team

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: int,
    db: AsyncSession = Depends(session),
    current_admin = Depends(require_admin),
):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    await db.delete(team)
    await db.commit()