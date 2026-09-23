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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from src.core.database import Base
from src.app.utils.uuid7 import uuid7

class ValidateQueryStatus:
    INITIALIZED      = "INITIALIZED"
    CREATED          = "CREATED"
    VALIDATING       = "VALIDATING"
    VALIDATED        = "VALIDATED"
    SEARCHING        = "SEARCHING"
    SEARCH_COMPLETED = "SEARCH_COMPLETED"
    SCORING          = "SCORING"
    COMPLETED        = "COMPLETED"
    FAILED           = "FAILED"

class ValidateFailureReason:
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SEARCH_ERROR     = "SEARCH_ERROR"
    SCORING_ERROR    = "SCORING_ERROR"
    TIMEOUT          = "TIMEOUT"
    UNKNOWN          = "UNKNOWN"

RECOVERABLE_STEPS = {
    ValidateQueryStatus.VALIDATING: ValidateQueryStatus.CREATED,
    ValidateQueryStatus.SEARCHING:  ValidateQueryStatus.VALIDATING,
    ValidateQueryStatus.SCORING:    ValidateQueryStatus.SEARCHING,
    ValidateQueryStatus.SEARCH_COMPLETED: ValidateQueryStatus.SEARCHING,
}

class ValidateQuery(Base):
    __tablename__ = "validate_queries"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    user_id              = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user_email           = Column(Text,    nullable=False, index=True)
    
    # ── Form Input Fields ─────────────────────────────────────────────
    title                = Column(Text,   nullable=False)
    description          = Column(Text,   nullable=False)
    industry             = Column(String, nullable=False, index=True)
    stage                = Column(String, nullable=False, index=True) # concept, prototype, live

    profile              = Column(JSONB,  default=dict, nullable=False)
    # conversation_history = Column(JSONB,  default=list, nullable=False)
    search_queries       = Column(JSONB,  default=list, nullable=True)
    runpod_job_id        = Column(String, nullable=True)

    status         = Column(String, default=ValidateQueryStatus.CREATED, nullable=False, index=True)
    failure_reason = Column(String, nullable=True)
    failed_at_step = Column(String, nullable=True)

    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    validated_at  = Column(DateTime(timezone=True), nullable=True)
    searched_at   = Column(DateTime(timezone=True), nullable=True)
    scored_at     = Column(DateTime(timezone=True), nullable=True)

    # ── helpers ───────────────────────────────────────────────────────
    @property
    def is_terminal(self) -> bool:
        return self.status in (ValidateQueryStatus.FAILED, ValidateQueryStatus.COMPLETED)

    @property
    def is_stuck(self) -> bool:
        return self.status in RECOVERABLE_STEPS

    def recover(self) -> None:
        safe = RECOVERABLE_STEPS.get(self.status)
        if not safe:
            return
        self.failed_at_step = _step_name(self.status)
        self.status         = safe
        self.failure_reason = ValidateFailureReason.TIMEOUT

    def start_step(self, in_progress_status: str) -> None:
        self.status         = in_progress_status
        self.failure_reason = None
        self.failed_at_step = None

    def complete_step(self, complete_status: str) -> None:
        self.status = complete_status
        _set_completion_timestamp(self)

    def fail_step(self, reason: str) -> None:
        self.failed_at_step = _step_name(self.status)
        self.status         = ValidateQueryStatus.FAILED
        self.failure_reason = reason


def _step_name(status: str) -> str:
    return {
        ValidateQueryStatus.VALIDATING: "validate",
        ValidateQueryStatus.SEARCHING:  "search",
        ValidateQueryStatus.SCORING:    "score",
    }.get(status, status.lower())


def _set_completion_timestamp(record: "ValidateQuery") -> None:
    now = datetime.now(timezone.utc)
    if record.status == ValidateQueryStatus.VALIDATING:
        record.validated_at = now
    elif record.status == ValidateQueryStatus.SEARCHING:
        record.searched_at  = now
    elif record.status == ValidateQueryStatus.COMPLETED:
        record.scored_at    = now


class ValidateQueryContext(Base):
    __tablename__ = "validate_query_contexts"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    query_id        = Column(UUID(as_uuid=True), ForeignKey("validate_queries.id"), nullable=False, index=True)
    market_signals  = Column(JSONB,       nullable=True)
    nlp_anchors     = Column(JSONB,       nullable=True)
    topic_boundary  = Column(JSONB,       nullable=True)
    schema_hints    = Column(JSONB,       nullable=True)
    provider        = Column(String(32),  nullable=True)
    model           = Column(String(128), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ValidateMarketSource(Base):
    __tablename__ = "validate_market_sources"
    __table_args__ = (
        UniqueConstraint("query_id", "url", name="uq_validate_market_source_query_url"),
    )

    id       = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    query_id = Column(UUID(as_uuid=True), ForeignKey("validate_queries.id"), nullable=False, index=True)

    search_query = Column(Text,        nullable=False)
    title        = Column(Text,        nullable=False)
    url          = Column(Text,        nullable=False, index=True)
    # snippet      = Column(Text,        nullable=True)
    # doc_id       = Column(String(255), nullable=True)

    # source_title    = Column(Text,                    nullable=True)
    # source_content  = Column(Text,                    nullable=True)
    # source_author   = Column(String(255),             nullable=True)
    # source_metadata = Column(JSONB,                   nullable=True)
    # fetch_ok        = Column(Boolean,                 nullable=True)
    # fetched_at      = Column(DateTime(timezone=True), nullable=True)

    # user_approved = Column(Boolean, default=False, nullable=True)
    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ValidateScoreSummary(Base):
    __tablename__ = "validate_score_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)

    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("validate_queries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # 1. Executive Verdict (2-3 sentences of candid institutional summary)
    executive_verdict = Column(Text, nullable=True)
    
    # 2. Aggregate Conviction Score (0-100 master score)
    aggregate_score = Column(Integer, nullable=True)

    # 3. Dimensional Scores (JSONB array of the 6 parameters: score, rationale, signal_strength)
    dimensional_scores = Column(JSONB, nullable=True)

    # 4. Competitive Landscape (JSONB array: competitor name, description, threat_level)
    competitive_landscape = Column(JSONB, nullable=True)

    # 5. Critical Vulnerabilities (JSONB array of strings detailing the top risks)
    critical_vulnerabilities = Column(JSONB, nullable=True)

    # 6. Actionable Next Steps (JSONB array of strings for the founder)
    actionable_next_steps = Column(JSONB, nullable=True)

    # 7. Evidentiary Sources (JSONB array of URLs used to ground the analysis)
    evidentiary_sources = Column(JSONB, nullable=True)
    
    # 8. All Sources (JSONB array of URLs used to ground the analysis)
    all_sources = Column(JSONB, nullable=True)

    # Metadata (For LLM token usage, provider info, etc.)
    meta = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)