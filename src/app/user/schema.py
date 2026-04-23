from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


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
    email: EmailStr  # Fixed: was `str: EmailStr` (field name was "str")


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    photo_url: str | None
    is_active: bool           # NEW
    created_at: datetime

    class Config:
        from_attributes = True


class ForgotPasswordRequest(BaseModel):
    email: str


class VerifyOTPRequest(BaseModel):
    email: str
    otp: str


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str


class MessageResponse(BaseModel):
    message: str


class ToggleUserStatusResponse(BaseModel):
    id: int
    is_active: bool
    message: str