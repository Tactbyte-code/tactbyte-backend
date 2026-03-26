from sqlalchemy import Column, Integer, String, Boolean, DateTime
from src.core.database import Base
from datetime import datetime, timezone

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String, unique=True, index=True)
    full_name = Column(String)
    email = Column(String, unique=True, index=True)
    photo_url = Column(String, nullable=True)
    hashed_password = Column(String, nullable=True)
    is_onboarded = Column(Boolean, default=False)
    
    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
class OTPRecord(Base):
    __tablename__ = "otp_records"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, index=True)
    otp = Column(String, nullable=False)
    reset_token = Column(String, nullable=True)
    is_used = Column(Boolean, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)