from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional, List


class ActivityPing(BaseModel):
    user_id: int
    action: Optional[str] = "active"


class DayCount(BaseModel):
    """Single point in the sparkline — one day's action count."""
    date: date
    count: int


class ActivityOut(BaseModel):
    user_id: int
    last_seen: datetime
    last_action: Optional[str]
    updated_at: datetime
    is_active: bool        # True when last_seen is within the last 24 hours
    days_ago: int          # 0 = today, 1 = yesterday, …
    sparkline: List[DayCount]  # last 30 days of daily counts

    class Config:
        from_attributes = True


class ActivityStatsOut(BaseModel):
    total_users: int
    total_tracked: int
    never_active: int
    active_30d: int
    active_24h: int
    inactive: int


class NewUsersOut(BaseModel):
    total_new: int
    google_new: int
    email_new: int
    user_ids: List[int]
    window_days: int


class BackfillOut(BaseModel):
    backfilled: int
    message: str