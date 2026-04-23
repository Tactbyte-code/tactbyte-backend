from pydantic import BaseModel, field_validator, model_validator
from typing import List, Optional
from app.masters.prices.schemas import PriceResponse


class PackageCreate(BaseModel):
    name:             str
    description:      str
    features:         List[str]
    monthly_price_id: Optional[int] = None
    annual_price_id:  Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Package name cannot be empty")
        return v.strip()

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Description cannot be empty")
        return v.strip()

    @field_validator("features")
    @classmethod
    def features_not_empty(cls, v):
        if not v:
            raise ValueError("At least one feature is required")
        return [f.strip() for f in v if f.strip()]

    @model_validator(mode="after")
    def at_least_one_price(self):
        if self.monthly_price_id is None and self.annual_price_id is None:
            raise ValueError("At least one pricing option (monthly or annual) is required")
        return self


class PackageUpdate(BaseModel):
    name:             Optional[str]       = None
    description:      Optional[str]       = None
    features:         Optional[List[str]] = None
    monthly_price_id: Optional[int]       = None
    annual_price_id:  Optional[int]       = None


class PackageResponse(BaseModel):
    id:            int
    name:          str
    description:   str
    features:      List[str]
    monthly_price: Optional[PriceResponse] = None
    annual_price:  Optional[PriceResponse] = None

    class Config:
        from_attributes = True