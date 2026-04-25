from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TicketReplyOut(BaseModel):
    id: int
    ticket_id: int
    message: str
    is_admin: int
    reply_type: str
    forwarded_from_team: Optional[str] = None
    forwarded_to_team: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketCreate(BaseModel):
    subject: str
    message: str
    user_email: str
    user_name: Optional[str] = None
    user_id: Optional[int] = None
    ticket_type: Optional[str] = "other"
    user_plan: Optional[str] = "free"
    # priority and assigned_team are auto-assigned from plan and type


class TicketOut(BaseModel):
    id: int
    ticket_id: Optional[str] = None   # e.g. "TIK001" — null on very old rows
    user_id: Optional[int]
    subject: str
    message: str
    status: str
    priority: str
    ticket_type: str
    user_plan: str
    assigned_team: str
    user_email: str
    user_name: Optional[str]
    created_at: datetime
    updated_at: datetime
    replies: List[TicketReplyOut]

    model_config = {"from_attributes": True}


class TicketStatusUpdate(BaseModel):
    status: str


class TicketPriorityUpdate(BaseModel):
    priority: str


class ReplyCreate(BaseModel):
    message: str


class ForwardTicket(BaseModel):
    to_team: str
    note: Optional[str] = None