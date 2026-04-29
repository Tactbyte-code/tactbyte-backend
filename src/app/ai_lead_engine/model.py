from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector
from src.core.database import Base
from src.app.utils.uuid7 import uuid7
from datetime import datetime, timezone


class Campaign(Base):
    __tablename__ = "campaigns"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True,  index=True)
    name        = Column(String, nullable=False)
    description = Column(String, nullable=True)
    intent      = Column(String, nullable=True)   # "People seeking services I offer"
    prompt      = Column(Text,   nullable=True)   # custom AI reply prompt
    website     = Column(String, nullable=True)

    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    keywords         = relationship("Keyword",         back_populates="campaign", cascade="all, delete-orphan")
    history          = relationship("CampaignHistory", back_populates="campaign", cascade="all, delete-orphan")
    leads            = relationship("Lead",            back_populates="campaign", cascade="all, delete-orphan")


class Keyword(Base):
    __tablename__ = "keywords"

    id          = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword     = Column(String,  nullable=False)
    match_type  = Column(String,  nullable=False, default="positive")  # "positive" | "negative"

    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    campaign    = relationship("Campaign", back_populates="keywords")


class CampaignHistory(Base):
    __tablename__ = "campaign_history"

    id          = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    action      = Column(String,  nullable=False)   # "created" | "updated" | "deleted"
    snapshot    = Column(JSONB,   nullable=True)    # full campaign state at time of change
    changed_fields = Column(JSONB, nullable=True)   # {"name": {"old": "X", "new": "Y"}}

    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    campaign    = relationship("Campaign", back_populates="history")
    leads       = relationship("Lead",     back_populates="campaign_history")


class Lead(Base):
    __tablename__ = "leads"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    campaign_id         = Column(Integer, ForeignKey("campaigns.id",        ondelete="CASCADE"), nullable=False, index=True)
    campaign_history_id = Column(Integer, ForeignKey("campaign_history.id", ondelete="CASCADE"), nullable=False, index=True)

    # ── Source ────────────────────────────────────────────────────
    platform            = Column(String(50),  nullable=False, default="reddit")  # "reddit" | "x"
    search_keyword      = Column(String,      nullable=False)

    # ── Scoring ───────────────────────────────────────────────────
    ai_score            = Column(Integer,     nullable=True)   # 1–10
    intent              = Column(Text,        nullable=True)   # AI-extracted intent summary
    category            = Column(String(100), nullable=True)   # "hiring_outsourcing" | "tool_request" | etc
    budget_signal       = Column(String(255), nullable=True)   # extracted budget string e.g. "$80/hr", "$15k-$20k"
    status              = Column(String(50),  nullable=False, default="new")  # "new" | "replied" | "ignored" | "converted"
    feedback            = Column(String,      nullable=True)

    # ── Embedding ─────────────────────────────────────────────────
    embedding           = Column(Vector(384), nullable=True)   # all-MiniLM-L6-v2
    embedding_model     = Column(String(100), nullable=True, default="all-MiniLM-L6-v2")
    embedding_text      = Column(Text,        nullable=True)   # what was embedded
    similarity_score    = Column(Float,       nullable=True)   # cosine similarity vs campaign keyword
    embedded_at         = Column(DateTime(timezone=True), nullable=True)

    created_at          = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # ── Relationships ─────────────────────────────────────────────
    campaign            = relationship("Campaign",        back_populates="leads")
    campaign_history    = relationship("CampaignHistory", back_populates="leads")
    post                = relationship("LeadPost",        back_populates="lead", uselist=False, cascade="all, delete-orphan")
    actions             = relationship("LeadAction",      back_populates="lead", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            "ix_leads_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class LeadPost(Base):
    """Platform-specific post data — currently Reddit + X."""
    __tablename__ = "lead_posts"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    lead_id         = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)

    # ── Shared fields ─────────────────────────────────────────────
    external_id     = Column(String(255), nullable=True)   # reddit post id or tweet id
    title           = Column(Text,        nullable=True)
    content         = Column(Text,        nullable=True)   # selftext or tweet body
    author          = Column(String(255), nullable=True)
    url             = Column(Text,        nullable=True)
    likes           = Column(Integer,     nullable=True)
    comments_count  = Column(Integer,     nullable=True)
    post_created_at = Column(DateTime(timezone=True), nullable=True)

    # ── Reddit-specific ───────────────────────────────────────────
    subreddit_id    = Column(String(255), nullable=True)
    subreddit       = Column(String(255), nullable=True)
    reddit_comments = Column(JSONB,       nullable=True)   # full comments payload

    # ── Fetch metadata ────────────────────────────────────────────
    fetch_ok        = Column(Boolean,     nullable=True)
    fetched_at      = Column(DateTime(timezone=True), nullable=True)

    # ── Relationship ──────────────────────────────────────────────
    lead            = relationship("Lead", back_populates="post")


class LeadAction(Base):
    """Tracks actions taken on a lead — replies, ignores, bookmarks, etc."""
    __tablename__ = "lead_actions"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid7, index=True)
    lead_id         = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)

    action_type     = Column(String(100), nullable=False)   # "replied" | "ignored" | "bookmarked" | "converted"
    note            = Column(Text,        nullable=True)    # optional note
    reply_text      = Column(Text,        nullable=True)    # if action_type == "replied"

    created_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # ── Relationship ──────────────────────────────────────────────
    lead            = relationship("Lead", back_populates="actions")