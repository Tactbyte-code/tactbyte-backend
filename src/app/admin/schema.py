from pydantic import BaseModel, EmailStr, Field
from src.app.admin.model import AdminRole
from typing import Any

class AdminLoginForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class AdminCreate(BaseModel):
    name:     str
    email:    EmailStr
    password: str
    role:     AdminRole = AdminRole.admin
    permissions:  dict[str, Any] = {}