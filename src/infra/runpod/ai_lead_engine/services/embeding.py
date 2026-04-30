# src/app/services/encoder.py

from datetime import datetime, timezone
from sentence_transformers import SentenceTransformer

# 🔥 load once globally (important for performance)
_model = SentenceTransformer("all-MiniLM-L6-v2")


# ── Text Builders ─────────────────────────────────────────────

def build_service_text(campaign) -> str:
    return f"""
Service:
{campaign.description or ""}

Intent:
{campaign.intent or ""}

This represents the type of service being offered.
""".strip()


def build_buyer_text(campaign) -> str:
    return f"""
A person who wants to hire or pay someone for:
{campaign.description or ""}

Their intent:
{campaign.intent or ""}

Strong buying signals:
- Asking how much something costs
- Looking for someone to hire or recommend
- Has a problem and needs someone to solve it
- Mentions budget, timeline, or project scope
- Asking for agency, freelancer, or service recommendations
- Frustrated with current solution and wants to replace it

These are NOT buyers:
- Professionals discussing their own work in this field
- People learning or asking how to do it themselves
- Job seekers looking for work
- People venting without intent to hire
""".strip()


# ── Generic Encoder ───────────────────────────────────────────

def encode_text(text: str) -> list[float]:
    if not text:
        return None
    return _model.encode(text).tolist()


# ── Campaign Encoder ─────────────────────────────────────────

def encode_campaign(campaign):
    service_text = build_service_text(campaign)
    buyer_text = build_buyer_text(campaign)

    service_vec = encode_text(service_text)
    buyer_vec = encode_text(buyer_text)

    return {
        "service_embedding": service_vec,
        "buyer_embedding": buyer_vec,
        "service_text": service_text,
        "buyer_text": buyer_text,
        "embedded_at": datetime.now(timezone.utc),
    }


# ── Apply to model (helper) ──────────────────────────────────

def apply_campaign_embedding(campaign):
    data = encode_campaign(campaign)

    campaign.service_embedding = data["service_embedding"]
    campaign.buyer_embedding = data["buyer_embedding"]

    campaign.service_embedding_text = data["service_text"]
    campaign.buyer_embedding_text = data["buyer_text"]

    campaign.embedded_at = data["embedded_at"]

    return campaign


def encode_lead_text(title: str, content: str):
    text = f"{title or ''}\n{content or ''}".strip()
    if not text:
        return None, None
    vector = _model.encode(text).tolist()
    return vector, text