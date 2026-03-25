from sqlalchemy import Column, Integer, String, ARRAY, ForeignKey, DateTime
from sqlalchemy.sql import func
from src.core.database import Base


class Onboarding(Base):
    __tablename__ = "onboarding"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    full_name  = Column(String, nullable=False)
    email      = Column(String, nullable=False)
    discovery  = Column(ARRAY(String), nullable=False)
    usage      = Column(ARRAY(String), nullable=False)
    occupation = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())