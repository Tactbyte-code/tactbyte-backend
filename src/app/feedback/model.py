from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, ARRAY
from src.core.database import Base
from datetime import datetime
import pytz

def indian_time():
    return datetime.now(pytz.timezone("Asia/Kolkata")).replace(tzinfo=None)

class Feedback(Base):
    __tablename__ = "feedback"

    id                = Column(Integer, primary_key=True, index=True)
    email             = Column(String, nullable=False)
    score             = Column(Integer, nullable=False)
    selected_features = Column(ARRAY(String), nullable=False, default=list)
    comments          = Column(Text, nullable=True)
    created_at        = Column(DateTime, default=indian_time)