from pydantic import BaseModel, field_validator, model_validator
from typing import List, Optional
from src.app.masters.prices.schemas import PriceResponse


class PackageCreate(BaseModel):
    name:         str
    package_type: str
    description:  str
    features:     List[str]
    is_free:      bool = False

    # Only required when is_free is False
    monthly_price_id: Optional[int] = None
    annual_price_id:  Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Package name cannot be empty")
        return v.strip()

    @field_validator("package_type")
    @classmethod
    def package_type_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Package type cannot be empty")
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
    def validate_pricing(self):
        if not self.is_free:
            if self.monthly_price_id is None and self.annual_price_id is None:
                raise ValueError(
                    "Paid plans require at least one price "
                    "(monthly or annual). Switch to Free if no price applies."
                )
        return self


class PackageUpdate(BaseModel):
    name:         Optional[str]       = None
    package_type: Optional[str]       = None
    description:  Optional[str]       = None
    features:     Optional[List[str]] = None
    is_free:      Optional[bool]      = None

    monthly_price_id: Optional[int] = None
    annual_price_id:  Optional[int] = None


class PackageResponse(BaseModel):
    id:           int
    name:         str
    package_type: str
    description:  str
    features:     List[str]
    is_free:      bool

    monthly_price: Optional[PriceResponse] = None
    annual_price:  Optional[PriceResponse] = None

    class Config:
        from_attributes = True