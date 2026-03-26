"""
Changes from original:
- LLM is a module-level singleton to use in langchain agents
- SarvaCompatibleChatOpenAI defined
"""

import os
import logging
from functools import lru_cache
from langchain_openai import ChatOpenAI
from src.core.settings import settings

log = logging.getLogger(__name__)

def _flatten_content(content) -> str:
    """Flatten LangChain message content to a plain string (Sarvam API requirement)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", str(block)))
        return " ".join(parts)
    return str(content)


class SarvaCompatibleChatOpenAI(ChatOpenAI):
    """ChatOpenAI that flattens message content to plain strings for Sarvam API."""

    def _get_request_payload(self, input_messages, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_messages, stop=stop, **kwargs)
        if "messages" in payload:
            flat = []
            for msg in payload["messages"]:
                if isinstance(msg.get("content"), (list, dict)):
                    msg = {**msg, "content": _flatten_content(msg["content"])}
                flat.append(msg)
            payload["messages"] = flat
        return payload


@lru_cache(maxsize=1)
def get_llm() -> SarvaCompatibleChatOpenAI:
    """Return the shared LLM instance (created once, reused on every call)."""
    return SarvaCompatibleChatOpenAI(
        model="sarvam-105b",
        openai_api_key=settings.SARVAM_API_KEY,
        openai_api_base="https://api.sarvam.ai/v1",
        temperature=0.3,
        max_tokens=2000,
    )


def _call_llm(system: str, user: str) -> str:
    """Single entry point for all LLM calls."""
    response = get_llm().invoke([
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ])
    return response.content