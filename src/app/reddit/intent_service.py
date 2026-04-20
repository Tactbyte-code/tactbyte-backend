from langchain.agents import create_agent
from langchain.messages import HumanMessage, AIMessage
from pydantic import BaseModel
from typing import Optional
from src.infra.langchain.llm import get_llm
from src.app.reddit.prompts import INTENT_SYSTEM_PROMPT
from src.app.reddit.model import FailureReason

MAX_CLARIFICATION_ROUNDS = 5


class IntentResult(BaseModel):
    needs_clarification: bool
    question:            Optional[str] = None
    options:             Optional[list[str]] = None


class IntentExtractionError(Exception):
    def __init__(self, message: str, failure_reason: FailureReason = FailureReason.LLM_ERROR):
        self.failure_reason = failure_reason
        super().__init__(message)


def get_agent():
    return create_agent(
        model=get_llm(),
        system_prompt=INTENT_SYSTEM_PROMPT,
        response_format=IntentResult,
    )


def build_messages(conversation_history: list[dict]) -> list:
    messages = []
    for turn in conversation_history:
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))
    return messages


async def extract_intent(conversation_history: list[dict]) -> IntentResult:
    agent    = get_agent()
    messages = build_messages(conversation_history)

    try:
        result = await agent.ainvoke({"messages": messages})
    except Exception as e:
        raise IntentExtractionError(
            f"Agent invocation failed: {str(e)}",
            FailureReason.LLM_ERROR,
        )

    return result["structured_response"]