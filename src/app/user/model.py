from sqlalchemy import Column, Integer, String, Boolean
from src.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String, unique=True, index=True)
    full_name = Column(String)
    email = Column(String, unique=True, index=True)
    photo_url = Column(String, nullable=True)
    hashed_password = Column(String, nullable=True)
    is_onboarded = Column(Boolean, default=False)