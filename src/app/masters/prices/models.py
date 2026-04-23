from sqlalchemy import Column, Integer, String, Float
from src.core.database import Base

class Price(Base):
    __tablename__ = "prices"

    id     = Column(Integer, primary_key=True, index=True)
    amount = Column(Float,   nullable=False)
    billed = Column(String,  nullable=False)