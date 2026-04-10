from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class FeedbackCreate(BaseModel):
    phone: Optional[str] = None
    message: str

class FeedbackResponse(BaseModel):
    id: int
    user_id: int
    full_name: str
    email: str
    phone: Optional[str]
    message: str
    created_at: datetime

    class Config:
        from_attributes = True