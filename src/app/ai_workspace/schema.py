from pydantic import BaseModel
from typing import Optional
from enum import Enum

class CreateWorkspace(BaseModel):
    name: str
    description: Optional[str] = None

class CreateChatSession(BaseModel):
    title: Optional[str] = "New chat"

class SendMessage(BaseModel):
    message: str