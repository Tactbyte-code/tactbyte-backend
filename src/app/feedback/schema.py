from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class FeedbackCreate(BaseModel):
    score: int                              
    selected_features: List[str]            
    comments: Optional[str] = None
    email: EmailStr


class FeedbackResponse(BaseModel):
    id: int
    email: str
    score: int
    selected_features: List[str]
    comments: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True