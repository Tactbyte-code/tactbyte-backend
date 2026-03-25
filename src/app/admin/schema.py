from pydantic import BaseModel, EmailStr, Field

class AdminLoginForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)