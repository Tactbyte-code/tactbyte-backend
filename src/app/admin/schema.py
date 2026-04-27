from pydantic import BaseModel, EmailStr, Field
from src.app.admin.model import AdminRole
from typing import Any


class AdminLoginForm(BaseModel):
    email:    EmailStr
    password: str = Field(min_length=6)


class AdminCreate(BaseModel):
    name:        str
    email:       EmailStr
    password:    str
    role:        AdminRole = AdminRole.admin
    permissions: dict[str, Any] = {}



class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyOtpRequest(BaseModel):
    email:    EmailStr
    otp:      str = Field(min_length=6, max_length=6)


class ResetPasswordRequest(BaseModel):
    reset_token:  str
    new_password: str = Field(min_length=6)




class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str = Field(min_length=6)