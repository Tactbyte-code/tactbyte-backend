from pydantic import BaseModel, field_validator
from typing import Literal


BilledType = Literal["monthly", "annually"]


class PriceCreate(BaseModel):
    amount: float
    billed: BilledType

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v):
        if v < 0:
            raise ValueError("Amount must be 0 or greater")
        return v


class PriceUpdate(BaseModel):
    amount: float
    billed: BilledType

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v):
        if v < 0:
            raise ValueError("Amount must be 0 or greater")
        return v


class PriceResponse(BaseModel):
    id:     int
    amount: float
    billed: str

    class Config:
        from_attributes = True