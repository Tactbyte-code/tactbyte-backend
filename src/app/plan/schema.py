from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class PurchasePlanRequest(BaseModel):
    plan: str
    credits: int
    
class UserPlanResponse(BaseModel):
    id: int
    user_id: int
    plan: str
    credits_total: int
    credits_used: int
    credits_remaining: int
    purchased_at: datetime
    expires_at: datetime
    expires_in_days: int
    last_query_at: Optional[datetime] = None    # ← new
    next_query_at: Optional[datetime] = None    # ← new (computed)
    can_query: bool = True                      # ← new (computed)
    cooldown_minutes_left: int = 0              # ← new (computed)

    class Config:
        from_attributes = True

class UserWithPlanResponse(BaseModel):
    id: int
    firebase_uid: str
    full_name: str
    email: str
    photo_url: Optional[str]
    is_onboarded: bool
    plan: Optional[UserPlanResponse] = None

    class Config:
        from_attributes = True