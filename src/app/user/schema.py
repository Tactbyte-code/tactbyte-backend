from pydantic import BaseModel, EmailStr
from typing import Optional

class GoogleSignUp(BaseModel):
    firebase_uid: str
    full_name: str
    email: EmailStr
    photo_url: Optional[str] = None

class EmailSignUp(BaseModel):
    firebase_uid: str
    full_name: str
    email: EmailStr
    password: str
    
class CheckProviderRequest(BaseModel):
    str: EmailStr