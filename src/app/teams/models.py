from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from datetime import datetime
from src.core.database import Base

class Team(Base):
    __tablename__="teams"
    
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(), nullable=False)
    slug        = Column(String(),  nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    color       = Column(String(),  nullable=False, default="#94a3b8")
    icon        = Column(String(),  nullable=True)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)