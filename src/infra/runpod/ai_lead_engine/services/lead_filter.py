from langchain.agents import create_agent
from src.infra.langchain.llm import get_llm
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
import asyncio
import random

LEAD_FILTER_SYSTEM_PROMPT = """
You are a lead qualification assistant.
Given a service description and a Reddit post title, score how likely
the post author is a potential customer for that service.

Score from 0–10:
- 8–10: Strong lead (clear pain point, actively seeking solution)
- 5–7:  Possible lead (related problem, may need the service)
- 0–4:  Not a lead (unrelated, venting, or already solved)

The person should be a BUYER — someone who wants to hire or pay for the service.
NOT someone who works in the field, is learning, or is job seeking.

Return score, brief reasoning, and is_lead (true if score >= 7).
"""

LEAD_SCORE_THRESHOLD = 7


class LeadScoreResult(BaseModel):
    score:     int   = Field(..., ge=0, le=10)
    reasoning: str
    is_lead:   bool  = Field(..., description="True if score >= 7")

    @model_validator(mode="after")
    def set_is_lead(self):
        self.is_lead = self.score >= LEAD_SCORE_THRESHOLD
        return self


class ScoreLeadBody(BaseModel):
    description:  str
    intent:       str
    reddit_title: str


class BatchScoreBody(BaseModel):
    description:   str
    intent:        str
    reddit_titles: list[str]


def get_lead_agent():
    return create_agent(
        model=get_llm(),
        system_prompt=LEAD_FILTER_SYSTEM_PROMPT,
        response_format=LeadScoreResult,
    )


async def score_lead(data: ScoreLeadBody) -> LeadScoreResult:
    agent = get_lead_agent()
    message = (
        f"Service Description: {data.description}\n"
        f"Target Intent: {data.intent}\n"
        f"Reddit Title: {data.reddit_title}\n\n"
        f"Score this title as a potential lead."
    )
    try:
        result = await agent.ainvoke({"messages": message})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result["structured_response"]


async def score_leads_batch(data: BatchScoreBody) -> list[LeadScoreResult]:
    agent     = get_lead_agent()
    semaphore = asyncio.Semaphore(10)

    async def score_one(title: str) -> LeadScoreResult | None:
        async with semaphore:
            try:
                result = await agent.ainvoke({
                    "messages": (
                        f"Service Description: {data.description}\n"
                        f"Target Intent: {data.intent}\n"
                        f"Reddit Title: {title}\n\n"
                        f"Score this title as a potential lead."
                    )
                })
                return result["structured_response"]
            except Exception as e:
                print(f"[lead_filter] Failed for title={title!r} — {e}")
                return None
            finally:
                await asyncio.sleep(1 + random.uniform(0.0, 0.5))

    results = await asyncio.gather(*[score_one(t) for t in data.reddit_titles])
    return [r for r in results if r is not None]