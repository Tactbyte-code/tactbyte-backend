from sqlalchemy import (
    Column, Integer, String, DateTime, Date, ForeignKey, UniqueConstraint
)
from datetime import datetime, timezone
from src.core.database import Base


class UserActivity(Base):
    """One row per user — stores the latest ping (last_seen, last_action)."""
    __tablename__ = "user_activity"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    last_seen   = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_action = Column(String(64), nullable=True)
    updated_at  = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UserActivityLog(Base):
    """One row per user per day — stores daily action count for sparkline graph."""
    __tablename__ = "user_activity_log"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date         = Column(Date, nullable=False)
    action_count = Column(Integer, default=1, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "date",
            name="uq_user_activity_log_user_date",
        ),
    )