# src/app/ai_lead_engine/keyword_service.py
from langchain.agents import create_agent
from src.infra.langchain.llm import get_llm
from src.app.ai_lead_engine.prompts import KEYWORD_SYSTEM_PROMPT
from src.app.ai_lead_engine.schema import GenerateKeywordsBody, KeywordsResult
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from src.app.ai_lead_engine.model import Keyword
from src.app.ai_lead_engine.schema import CreateKeywordBody, GenerateKeywordsBody
from src.app.ai_lead_engine.campaign_service import get_campaign
from src.app.user.model import User



def get_agent():
    return create_agent(
        model=get_llm(),
        system_prompt=KEYWORD_SYSTEM_PROMPT,
        response_format=KeywordsResult,
    )


async def generate_keywords(data: GenerateKeywordsBody) -> KeywordsResult:
    agent = get_agent()

    messages = (
        f"Intent: {data.intent}\n"
        f"Description: {data.description}\n\n"
        f"Generate 5 Reddit-style phrases that match this intent and description."
    )

    try:
        result = await agent.ainvoke({"messages": messages})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return result["structured_response"]


async def get_keywords(db: AsyncSession, user: User, campaign_id: int) -> list[Keyword]:
    await get_campaign(db, user, campaign_id)  # ownership check
    result = await db.execute(
        select(Keyword).where(Keyword.campaign_id == campaign_id)
    )
    return result.scalars().all()


async def create_keyword(db: AsyncSession, user: User, campaign_id: int, body: CreateKeywordBody) -> Keyword:
    await get_campaign(db, user, campaign_id)  # ownership check

    keyword = Keyword(
        campaign_id=campaign_id,
        keyword=body.keyword,
        match_type=body.match_type,
    )
    db.add(keyword)
    await db.commit()
    await db.refresh(keyword)
    return keyword


async def delete_keyword(db: AsyncSession, user: User, campaign_id: int, keyword_id: int) -> None:
    await get_campaign(db, user, campaign_id)  # ownership check

    result = await db.execute(
        select(Keyword).where(Keyword.id == keyword_id, Keyword.campaign_id == campaign_id)
    )
    keyword = result.scalar_one_or_none()
    if not keyword:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")

    await db.delete(keyword)
    await db.commit()