# app/routers/admin/models.py
import enum
from sqlalchemy import Column, Integer, String, Enum, JSON
from src.core.database import Base


class AdminRole(str, enum.Enum):
    admin       = "admin"
    super_admin = "super_admin"


class Admin(Base):
    __tablename__  = "admins"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String, nullable=False)
    email           = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    session_token   = Column(String, nullable=True, default=None)
    role            = Column(Enum(AdminRole), nullable=False, default=AdminRole.admin)
    permissions     = Column(JSON, nullable=False, default=dict)  