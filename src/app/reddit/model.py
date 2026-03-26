import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from src.core.database import Base
from src.app.utils.uuid7 import uuid7


class QueryStatus:
    CREATED         = "CREATED"
    CLARIFYING      = "CLARIFYING"
    CLARIFIED       = "CLARIFIED"
    WEB_SEARCHING   = "WEB_SEARCHING"
    SEARCH_COMPLETE = "SEARCH_COMPLETE"
    SUMMARIZING     = "SUMMARIZING"
    COMPLETED       = "COMPLETED"
    FAILED          = "FAILED"


class FailureReason:
    SEARCH_ERROR        = "SEARCH_ERROR"
    NO_RESULTS          = "NO_RESULTS"
    LLM_ERROR           = "LLM_ERROR"
    SUMMARIZATION_ERROR = "SUMMARIZATION_ERROR"
    TIMEOUT             = "TIMEOUT"
    UNKNOWN             = "UNKNOWN"



RECOVERABLE_STEPS = {
    QueryStatus.CLARIFYING:    QueryStatus.CREATED,
    QueryStatus.WEB_SEARCHING: QueryStatus.CLARIFIED,
    QueryStatus.SUMMARIZING:   QueryStatus.SEARCH_COMPLETE,
}



class RedditQuery(Base):
    __tablename__ = "reddit_queries"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    user_id              = Column(Integer, ForeignKey("users.id"), nullable=True,  index=True)
    user_email           = Column(Text,    nullable=False, index=True)
    query                = Column(Text,    nullable=False)
    profile              = Column(JSONB,   default=dict,  nullable=False)
    clarification_count  = Column(Integer, default=0,     nullable=False)
    conversation_history = Column(JSONB,   default=list,  nullable=False)
    search_queries       = Column(JSONB,   default=list,  nullable=True)
    runpod_job_id        = Column(String,  nullable=True)

    status         = Column(String, default=QueryStatus.CREATED, nullable=False, index=True)
    failure_reason = Column(String, nullable=True)
    failed_at_step = Column(String, nullable=True)

    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    clarified_at  = Column(DateTime(timezone=True), nullable=True)
    searched_at   = Column(DateTime(timezone=True), nullable=True)
    summarized_at = Column(DateTime(timezone=True), nullable=True)

    # ── helpers ───────────────────────────────────────────────────────
    @property
    def is_terminal(self) -> bool:
        return self.status in (QueryStatus.FAILED, QueryStatus.COMPLETED)

    @property
    def is_stuck(self) -> bool:
        return self.status in RECOVERABLE_STEPS

    def recover(self) -> None:
        safe = RECOVERABLE_STEPS.get(self.status)
        if not safe:
            return
        self.failed_at_step = _step_name(self.status)
        self.status         = safe
        self.failure_reason = FailureReason.TIMEOUT

    def start_step(self, in_progress_status: str) -> None:
        self.status         = in_progress_status
        self.failure_reason = None
        self.failed_at_step = None

    def complete_step(self, complete_status: str) -> None:
        self.status = complete_status
        _set_completion_timestamp(self)

    def fail_step(self, reason: str) -> None:
        self.failed_at_step = _step_name(self.status)
        self.status         = QueryStatus.FAILED
        self.failure_reason = reason

def _step_name(status: str) -> str:
    return {
        QueryStatus.CLARIFYING:    "clarify",
        QueryStatus.WEB_SEARCHING: "search",
        QueryStatus.SUMMARIZING:   "summarize",
    }.get(status, status.lower())


def _set_completion_timestamp(record: "RedditQuery") -> None:
    now = datetime.now(timezone.utc)
    if record.status == QueryStatus.CLARIFIED:
        record.clarified_at  = now
    elif record.status == QueryStatus.SEARCH_COMPLETE:
        record.searched_at   = now
    elif record.status == QueryStatus.COMPLETED:
        record.summarized_at = now



class RedditQueryContext(Base):
    __tablename__ = "reddit_query_contexts"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    query_id        = Column(UUID(as_uuid=True), ForeignKey("reddit_queries.id"), nullable=False, index=True)
    user_query      = Column(Text,        nullable=True)
    queries         = Column(JSONB,       nullable=True)
    nlp_anchors     = Column(JSONB,       nullable=True)
    topic_boundary  = Column(JSONB,       nullable=True)
    schema_hints    = Column(JSONB,       nullable=True)
    provider        = Column(String(32),  nullable=True)
    modelel         = Column(String(128), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class RedditPost(Base):
    __tablename__ = "reddit_posts"
    __table_args__ = (
        UniqueConstraint("query_id", "url", name="uq_reddit_post_query_url"),
    )

    id       = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    query_id = Column(UUID(as_uuid=True), ForeignKey("reddit_queries.id"), nullable=False, index=True)

    # ── Vertex AI Search ──────────────────────────────────────────────
    search_query = Column(Text,        nullable=False)
    title        = Column(Text,        nullable=False)
    url          = Column(Text,        nullable=False, index=True)
    snippet      = Column(Text,        nullable=True)
    doc_id       = Column(String(255), nullable=True)

    # ── Reddit API — point-in-time snapshot ───────────────────────────
    reddit_id           = Column(String(255),             nullable=True)
    reddit_title        = Column(Text,                    nullable=True)
    reddit_selftext     = Column(Text,                    nullable=True)
    reddit_author       = Column(String(255),             nullable=True)
    reddit_subreddit_id = Column(String(255),             nullable=True)
    reddit_subreddit    = Column(String(255),             nullable=True)
    reddit_score        = Column(Integer,                 nullable=True)
    reddit_num_comments = Column(Integer,                 nullable=True)
    reddit_created_utc  = Column(DateTime(timezone=True), nullable=True)
    reddit_url          = Column(Text,                    nullable=True)
    reddit_fetch_ok     = Column(Boolean,                 nullable=True)
    reddit_fetched_at   = Column(DateTime(timezone=True), nullable=True)
    reddit_comments     = Column(JSONB,                   nullable=True)

    user_approved = Column(Boolean, default=False, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)



class RedditSummary(Base):
    __tablename__ = "reddit_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)

    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reddit_queries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    search_query      = Column(Text,    nullable=False)
    subreddit         = Column(Text,    nullable=True)
    analyzed_at       = Column(Text,    nullable=True)
    direct_answer     = Column(Text,    nullable=True)
    executive_summary = Column(Text,    nullable=True)
    overall_sentiment = Column(Text,    nullable=True)
    total_signals     = Column(Integer, nullable=True)

    themes                = Column(JSONB, nullable=True)
    market_signals        = Column(JSONB, nullable=True)
    actionable_next_steps = Column(JSONB, nullable=True)
    meta                  = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)