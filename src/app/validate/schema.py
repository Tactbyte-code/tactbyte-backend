from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class ValidateQueryInput(BaseModel):
    title: str
    description: str
    industry: str
    stage: str
    profile: Optional[Dict[str, Any]] = None

class UpdateValidateStatus(BaseModel):
    status: str
    failure_reason: Optional[str] = None
    failed_at_step: Optional[str] = None