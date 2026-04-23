from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.database import session
from src.app.middleware.auth import require_admin
from app.masters.packages import models, schemas

router = APIRouter(prefix="/packages", tags=["Packages"])


# ── GET /packages/ ─────────────────────────────────────────────
@router.get("/", response_model=list[schemas.PackageResponse])
async def get_all_packages(
    db: AsyncSession = Depends(session),
):
    result = await db.execute(
        select(models.Package).order_by(models.Package.id.asc())
    )
    return result.scalars().all()


# ── GET /packages/{package_id} ─────────────────────────────────
@router.get("/{package_id}", response_model=schemas.PackageResponse)
async def get_package(
    package_id: int,
    db: AsyncSession = Depends(session),
):
    result = await db.execute(
        select(models.Package).where(models.Package.id == package_id)
    )
    pkg = result.scalar_one_or_none()

    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    return pkg


# ── POST /packages/ ────────────────────────────────────────────
@router.post("/", response_model=schemas.PackageResponse)
async def create_package(
    data: schemas.PackageCreate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    pkg = models.Package(
        name=data.name,
        description=data.description,
        features=data.features,
        monthly_price_id=data.monthly_price_id,
        annual_price_id=data.annual_price_id,
    )

    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)

    return pkg


# ── PUT /packages/{package_id} ─────────────────────────────────
@router.put("/{package_id}", response_model=schemas.PackageResponse)
async def update_package(
    package_id: int,
    data: schemas.PackageUpdate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        select(models.Package).where(models.Package.id == package_id)
    )
    pkg = result.scalar_one_or_none()

    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    if data.name is not None:
        pkg.name = data.name
    if data.description is not None:
        pkg.description = data.description
    if data.features is not None:
        pkg.features = data.features

    # allow null updates
    if "monthly_price_id" in data.model_fields_set:
        pkg.monthly_price_id = data.monthly_price_id
    if "annual_price_id" in data.model_fields_set:
        pkg.annual_price_id = data.annual_price_id

    await db.commit()
    await db.refresh(pkg)

    return pkg


# ── DELETE /packages/{package_id} ──────────────────────────────
@router.delete("/{package_id}")
async def delete_package(
    package_id: int,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        select(models.Package).where(models.Package.id == package_id)
    )
    pkg = result.scalar_one_or_none()

    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    await db.delete(pkg)
    await db.commit()

    return {"message": "Package deleted successfully"}