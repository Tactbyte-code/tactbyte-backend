from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector
from src.core.database import Base
from src.app.utils.uuid7 import uuid7
from datetime import datetime, timezone


class Workspace(Base):
    __tablename__ = "workspaces"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=True,  index=True)
    name         = Column(String(255), nullable=False)
    description  = Column(Text)
    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    sources      = relationship("Source", back_populates="workspace", cascade="all, delete-orphan")
    sessions     = relationship("ChatSession", back_populates="workspace", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"

    id             = Column(Integer, primary_key=True, index=True)
    workspace_id   = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    filename       = Column(String(512))
    source_type    = Column(String(50))   # "pdf", "url", "txt", "docx"
    s3_key         = Column(String(1024)) # R2 object key
    status         = Column(String(50), default="pending")  # pending → processing → ready → failed
    meta           = Column(JSONB, default=dict)  # page count, mime type, etc.
    created_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    workspace      = relationship("Workspace", back_populates="sources")
    # chunks         = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")
    # embed_jobs     = relationship("EmbeddingJob", back_populates="source")

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id           = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    title        = Column(String(255), default="New chat")
    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    workspace    = relationship("Workspace", back_populates="sessions")