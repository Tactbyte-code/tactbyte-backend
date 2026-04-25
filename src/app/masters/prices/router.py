from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.database import session
from src.app.middleware.auth import require_admin
from src.app.masters.prices import models, schemas
from src.app.masters.packages.models import Package

router = APIRouter(prefix="/prices", tags=["Prices"])


@router.get("/", response_model=list[schemas.PriceResponse])
async def get_all_prices(db: AsyncSession = Depends(session)):
    result = await db.execute(
        select(models.Price).order_by(models.Price.billed, models.Price.amount)
    )
    return result.scalars().all()


@router.get("/{price_id}", response_model=schemas.PriceResponse)
async def get_price(price_id: int, db: AsyncSession = Depends(session)):
    result = await db.execute(
        select(models.Price).where(models.Price.id == price_id)
    )
    price = result.scalar_one_or_none()
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")
    return price


@router.post("/", response_model=schemas.PriceResponse)
async def create_price(
    data: schemas.PriceCreate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    price = models.Price(amount=data.amount, billed=data.billed)
    db.add(price)
    await db.commit()
    await db.refresh(price)
    return price


@router.put("/{price_id}", response_model=schemas.PriceResponse)
async def update_price(
    price_id: int,
    data: schemas.PriceUpdate,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        select(models.Price).where(models.Price.id == price_id)
    )
    price = result.scalar_one_or_none()
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")

    price.amount = data.amount
    price.billed = data.billed
    await db.commit()
    await db.refresh(price)
    return price


@router.delete("/{price_id}")
async def delete_price(
    price_id: int,
    db: AsyncSession = Depends(session),
    current_admin=Depends(require_admin),
):
    result = await db.execute(
        select(models.Price).where(models.Price.id == price_id)
    )
    price = result.scalar_one_or_none()
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")

    # Check if used in any package
    pkg_result = await db.execute(
        select(Package).where(
            (Package.monthly_price_id == price_id) |
            (Package.annual_price_id == price_id)
        )
    )
    if pkg_result.scalars().first():
        raise HTTPException(
            status_code=409,
            detail="Price is assigned to one or more packages. Remove it from all packages before deleting."
        )

    await db.delete(price)
    await db.commit()
    return {"message": "Price deleted successfully"}