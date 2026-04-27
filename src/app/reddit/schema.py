from pydantic import BaseModel
from typing import Optional
from enum import Enum

class QueryInput(BaseModel):
    query: str
    
class ClarifyingAnswerInput(BaseModel):
    answer: Optional[str] = None
    selected_option: Optional[str] = None
    skip: Optional[bool] = False
    
class UpdatePostApproval(BaseModel):
    user_approved: bool