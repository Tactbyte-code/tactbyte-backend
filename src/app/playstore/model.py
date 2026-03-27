from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.core.database import Base
from src.app.utils.uuid7 import uuid7


class PlaystoreQueryStatus:
    CREATED         = "CREATED"
    FETCHING        = "FETCHING"
    FETCH_COMPLETE  = "FETCH_COMPLETE"
    SUMMARIZING     = "SUMMARIZING"
    COMPLETED       = "COMPLETED"
    FAILED          = "FAILED"


class PlaystoreFailureReason:
    FETCH_ERROR         = "FETCH_ERROR"
    NO_RESULTS          = "NO_RESULTS"
    LLM_ERROR           = "LLM_ERROR"
    SUMMARIZATION_ERROR = "SUMMARIZATION_ERROR"
    TIMEOUT             = "TIMEOUT"
    UNKNOWN             = "UNKNOWN"


class PlaystoreQuery(Base):
    __tablename__ = "playstore_queries"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user_email   = Column(Text,    nullable=False, index=True)
    app_id       = Column(Text,    nullable=False)           # e.g. com.spotify.music
    app_name     = Column(Text,    nullable=True)            # filled after fetch
    runpod_job_id = Column(String, nullable=True)

    status         = Column(String, default=PlaystoreQueryStatus.CREATED, nullable=False, index=True)
    failure_reason = Column(String, nullable=True)
    failed_at_step = Column(String, nullable=True)

    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    fetched_at   = Column(DateTime(timezone=True), nullable=True)
    summarized_at = Column(DateTime(timezone=True), nullable=True)

    # ── helpers ──────────────────────────────────────────────────────────────

    @property
    def is_terminal(self) -> bool:
        return self.status in (PlaystoreQueryStatus.FAILED, PlaystoreQueryStatus.COMPLETED)

    def start_step(self, in_progress_status: str) -> None:
        self.status         = in_progress_status
        self.failure_reason = None
        self.failed_at_step = None

    def complete_step(self, complete_status: str) -> None:
        self.status = complete_status
        _set_completion_timestamp(self)

    def fail_step(self, reason: str) -> None:
        self.failed_at_step = _step_name(self.status)
        self.status         = PlaystoreQueryStatus.FAILED
        self.failure_reason = reason


def _step_name(status: str) -> str:
    return {
        PlaystoreQueryStatus.FETCHING:    "fetch",
        PlaystoreQueryStatus.SUMMARIZING: "summarize",
    }.get(status, status.lower())


def _set_completion_timestamp(record: "PlaystoreQuery") -> None:
    now = datetime.now(timezone.utc)
    if record.status == PlaystoreQueryStatus.FETCH_COMPLETE:
        record.fetched_at   = now
    elif record.status == PlaystoreQueryStatus.COMPLETED:
        record.summarized_at = now


class PlaystoreReview(Base):
    __tablename__ = "playstore_reviews"
    __table_args__ = (
        UniqueConstraint("query_id", "review_id", name="uq_playstore_review_query_review"),
    )

    id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    query_id  = Column(UUID(as_uuid=True), ForeignKey("playstore_queries.id"), nullable=False, index=True)
    app_id    = Column(Text,    nullable=False, index=True)

    review_id      = Column(String(255), nullable=True)
    username       = Column(Text,        nullable=True)
    content        = Column(Text,        nullable=True)
    score          = Column(Integer,     nullable=True)   # 1-5 stars
    thumbs_up      = Column(Integer,     nullable=True)
    review_created = Column(DateTime(timezone=True), nullable=True)
    reply_content  = Column(Text,        nullable=True)
    reply_date     = Column(DateTime(timezone=True), nullable=True)

    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    
    

class PlaystoreSummary(Base):
    __tablename__ = "playstore_summaries"
 
    id       = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("playstore_queries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
 
    app_id   = Column(Text, nullable=False)
    app_name = Column(Text, nullable=True)
 
    analyzed_at       = Column(Text,    nullable=True)
    direct_answer     = Column(Text,    nullable=True)
    executive_summary = Column(Text,    nullable=True)
    overall_sentiment = Column(Text,    nullable=True)
    total_signals     = Column(Integer, nullable=True)
    average_rating    = Column(Text,    nullable=True)
 
    themes                = Column(JSONB, nullable=True)
    market_signals        = Column(JSONB, nullable=True)
    actionable_next_steps = Column(JSONB, nullable=True)
    rating_breakdown      = Column(JSONB, nullable=True)
    meta                  = Column(JSONB, nullable=True)
 
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)