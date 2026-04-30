# src/app/ai_lead_engine/schema.py

from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime

# ── Keywords ───────────────────────────────────────────────────────────────────

class GenerateKeywordsBody(BaseModel):
    description: str
    intent: Optional[str] = None         # helps AI generate better keywords
    website: Optional[str] = None        # scraped to extract more context


class KeywordsResult(BaseModel):
    keywords: list[str]


class CreateKeywordBody(BaseModel):
    keyword: str
    match_type: str = Field(default="positive", pattern="^(positive|negative)$")


class KeywordResponse(BaseModel):
    id: int
    campaign_id: int
    keyword: str
    match_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Campaign ───────────────────────────────────────────────────────────────────

class CreateCampaignBody(BaseModel):
    name: str
    description: Optional[str] = None
    intent: Optional[str] = None
    prompt: Optional[str] = None
    website: Optional[str] = None
    keywords: Optional[List[CreateKeywordBody]] = []


class UpdateCampaignBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    intent: Optional[str] = None
    prompt: Optional[str] = None
    website: Optional[str] = None


class CampaignResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    intent: Optional[str]
    prompt: Optional[str]
    website: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    last_synced_at: Optional[datetime]  = None
    next_allowed_at: Optional[datetime]  = None

    model_config = {"from_attributes": True}


# ── Campaign History ───────────────────────────────────────────────────────────

class CampaignHistoryResponse(BaseModel):
    id: int
    campaign_id: int
    action: str                          # "created" | "updated" | "deleted"
    snapshot: Optional[dict] = None
    changed_fields: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Lead Filters ───────────────────────────────────────────────────────────────

class LeadFilterParams(BaseModel):
    min_score: Optional[int] = None      # e.g. 8 → only score >= 8
    history_id: Optional[int] = None     # filter by scan run


# ── Lead Post ─────────────────────────────────────────────────────────────────

class LeadPostResponse(BaseModel):
    id: UUID
    external_id: Optional[str]
    title: Optional[str]
    content: Optional[str]
    author: Optional[str]
    url: Optional[str]
    likes: Optional[int]
    comments_count: Optional[int]
    subreddit: Optional[str]
    subreddit_id: Optional[str]
    reddit_comments: Optional[dict | list] = None
    fetch_ok: Optional[bool]
    fetched_at: Optional[datetime]
    post_created_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Lead ──────────────────────────────────────────────────────────────────────

class LeadResponse(BaseModel):
    id: UUID
    campaign_id: int
    campaign_history_id: int
    platform: str
    search_keyword: str
    ai_score: Optional[int]
    intent: Optional[str]
    category: Optional[str]
    budget_signal: Optional[str]
    status: str
    feedback: Optional[str]
    similarity_score: Optional[float]
    embedding_model: Optional[str]
    embedded_at: Optional[datetime]
    created_at: datetime

    # Nested
    post: Optional[LeadPostResponse] = None

    model_config = {"from_attributes": True}


class LeadDetailResponse(LeadResponse):
    """Extended response that includes actions — used on single lead fetch."""
    actions: list["LeadActionResponse"] = []

    model_config = {"from_attributes": True}


class SimilarLeadResponse(BaseModel):
    id: UUID
    status: str
    ai_score: Optional[int]
    category: Optional[str]
    platform: str
    search_keyword: str
    title: Optional[str]
    url: Optional[str]
    similarity: float


# ── Lead Actions ───────────────────────────────────────────────────────────────

class CreateLeadActionBody(BaseModel):
    action_type: str = Field(pattern="^(replied|ignored|bookmarked|converted)$")
    note: Optional[str] = None
    reply_text: Optional[str] = None     # populated when action_type == "replied"


class LeadActionResponse(BaseModel):
    id: UUID
    lead_id: UUID
    action_type: str
    note: Optional[str]
    reply_text: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Update lead status ────────────────────────────────────────────────────────

class UpdateLeadStatusBody(BaseModel):
    status: str = Field(pattern="^(new|replied|ignored|converted)$")


# Resolve forward reference for LeadDetailResponse
LeadDetailResponse.model_rebuild()