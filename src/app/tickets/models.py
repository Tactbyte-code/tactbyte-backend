from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from src.core.database import Base


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"


class TicketPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TicketType(str, enum.Enum):
    login_issue = "login_issue"
    ai_performance = "ai_performance"
    payment = "payment"
    search_results = "search_results"
    feature_request = "feature_request"
    billing = "billing"
    account = "account"
    other = "other"


class UserPlan(str, enum.Enum):
    free = "free"
    starter = "starter"
    pro = "pro"


# Pro → High, Starter → Medium, Free → Low
PLAN_PRIORITY_MAP = {
    UserPlan.pro: TicketPriority.high,
    UserPlan.starter: TicketPriority.medium,
    UserPlan.free: TicketPriority.low,
}

TYPE_TEAM_MAP = {
    TicketType.login_issue: "auth",
    TicketType.ai_performance: "ai",
    TicketType.payment: "payments",
    TicketType.search_results: "search",
    TicketType.feature_request: "product",
    TicketType.billing: "billing",
    TicketType.account: "account",
    TicketType.other: "general",
}


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)

    # Human-readable display ID: TIK001, TIK002, …
    # Set after first flush in create_ticket so we have the auto-increment id.
    ticket_id = Column(String(20), unique=True, index=True, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    subject = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(Enum(TicketStatus), default=TicketStatus.open, nullable=False)
    priority = Column(Enum(TicketPriority), default=TicketPriority.medium, nullable=False)
    ticket_type = Column(Enum(TicketType), default=TicketType.other, nullable=False)
    user_plan = Column(Enum(UserPlan), default=UserPlan.free, nullable=False)
    assigned_team = Column(String(50), default="general", nullable=False)
    user_email = Column(String(255), nullable=False)
    user_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    replies = relationship(
        "TicketReply",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketReply.created_at",
    )


class TicketReply(Base):
    __tablename__ = "ticket_replies"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    message = Column(Text, nullable=False)
    is_admin = Column(Integer, default=0)
    reply_type = Column(String(20), default="message", nullable=False)
    forwarded_from_team = Column(String(50), nullable=True)
    forwarded_to_team = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="replies")