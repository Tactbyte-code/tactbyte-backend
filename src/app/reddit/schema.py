from pydantic import BaseModel
from typing import Optional
from enum import Enum

class QueryInput(BaseModel):
    query: str
    
class ClarifyingAnswerInput(BaseModel):
    answer: str
    
class UpdatePostApproval(BaseModel):
    user_approved: bool