from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.database import session
from src.app.middleware.auth import require_admin
from src.app.masters.packages import models, schemas

router = APIRouter(prefix="/packages", tags=["Packages"])


def _with_prices():
    """Reusable selectinload options for price relationships."""
    return [
        selectinload(models.Package.monthly_price),
        selectinload(models.Package.annual_price),
    ]


@router.get("/", response_model=list[schemas.PackageResponse])
async def get_all_packages(db: AsyncSession = Depends(session)):
    result = await db.execute(
        select(models.Package)
        .options(*_with_prices())
        .order_by(models.Package.id.asc())
    )
    return result.scalars().all()


@router.get("/{package_id}", response_model=schemas.PackageResponse)
async def get_package(package_id: int, db: AsyncSession = Depends(session)):
    result = await db.execute(
        select(models.Package)
        .options(*_with_prices())
        .where(models.Package.id == package_id)
    )
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    return pkg


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

    # Re-fetch with relationships loaded instead of relying on refresh
    result = await db.execute(
        select(models.Package)
        .options(*_with_prices())
        .where(models.Package.id == pkg.id)
    )
    return result.scalar_one()


@router.put("/{package_id}", response_model=schemas.PackageResponse)
async def update_package(
    package_id: int,
    data: schemas.PackageUpdate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        select(models.Package)
        .options(*_with_prices())
        .where(models.Package.id == package_id)
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
    if "monthly_price_id" in data.model_fields_set:
        pkg.monthly_price_id = data.monthly_price_id
    if "annual_price_id" in data.model_fields_set:
        pkg.annual_price_id = data.annual_price_id

    await db.commit()

    # Re-fetch to get updated relationships
    result = await db.execute(
        select(models.Package)
        .options(*_with_prices())
        .where(models.Package.id == package_id)
    )
    return result.scalar_one()


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