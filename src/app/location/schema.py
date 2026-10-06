from pydantic import BaseModel, Field
from typing import Any, Dict

class CoordinatesPayload(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude between -90 and 90")
    lng: float = Field(..., ge=-180.0, le=180.0, description="Longitude between -180 and 180")


class LocationResponse(BaseModel):
    full_address: str
    city: str
    state: str
    country: str
    postal_code: str
    raw_address: Dict[str, Any]