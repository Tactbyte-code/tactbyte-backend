from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from src.core.database import Base
from datetime import datetime
import pytz

def indian_time():
    return datetime.now(pytz.timezone("Asia/Kolkata")).replace(tzinfo=None)

class Contact(Base):
    __tablename__ = "contact"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=indian_time)  # ← no timezone=True