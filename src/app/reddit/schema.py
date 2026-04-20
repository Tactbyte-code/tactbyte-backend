from pydantic import BaseModel
from typing import Optional
from enum import Enum

class QueryInput(BaseModel):
    query: str
    
class ClarifyingAnswerInput(BaseModel):
    answer: str
    selected_option: Optional[str] = None
    
class UpdatePostApproval(BaseModel):
    user_approved: bool