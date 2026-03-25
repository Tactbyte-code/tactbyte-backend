from pydantic import BaseModel
from datetime import datetime


class OnboardingCreate(BaseModel):
    discovery:  list[str]
    usage:      list[str]
    occupation: str