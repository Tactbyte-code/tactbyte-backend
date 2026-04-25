from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class TeamCreate(BaseModel):
    name:        str              = Field(..., min_length=1, max_length=100)
    slug:        str              = Field(..., min_length=1, max_length=50, pattern=r'^[a-z0-9_-]+$')
    description: Optional[str]   = None
    color:       str              = Field(default="#94a3b8")
    icon:        Optional[str]    = None
    is_active:   bool             = True


class TeamUpdate(BaseModel):
    name:        Optional[str]    = Field(None, min_length=1, max_length=100)
    slug:        Optional[str]    = Field(None, min_length=1, max_length=50, pattern=r'^[a-z0-9_-]+$')
    description: Optional[str]   = None
    color:       Optional[str]   = None
    icon:        Optional[str]    = None
    is_active:   Optional[bool]  = None


class TeamOut(BaseModel):
    id:          int
    name:        str
    slug:        str
    description: Optional[str]
    color:       str
    icon:        Optional[str]
    is_active:   bool
    created_at:  datetime
    updated_at:  datetime

    model_config = {"from_attributes": True}