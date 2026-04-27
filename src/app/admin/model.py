import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Enum, JSON, DateTime
from src.core.database import Base


class AdminRole(str, enum.Enum):
    admin       = "admin"
    super_admin = "super_admin"


class Admin(Base):
    __tablename__ = "admins"

    id                  = Column(Integer, primary_key=True, index=True)
    name                = Column(String, nullable=False)
    email               = Column(String, unique=True, index=True, nullable=False)
    hashed_password     = Column(String, nullable=False)
    session_token       = Column(String, nullable=True, default=None)
    role                = Column(Enum(AdminRole), nullable=False, default=AdminRole.admin)
    permissions         = Column(JSON, nullable=False, default=dict)

    otp_hash            = Column(String,   nullable=True, default=None)
    otp_expiry          = Column(DateTime, nullable=True, default=None)
    otp_attempts        = Column(Integer,  nullable=False, default=0)
    reset_token         = Column(String,   nullable=True, default=None)
    reset_token_expiry  = Column(DateTime, nullable=True, default=None)