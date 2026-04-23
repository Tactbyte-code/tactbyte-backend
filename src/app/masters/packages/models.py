from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import relationship
from src.core.database import Base


class Package(Base):
    __tablename__ = "packages"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String,  nullable=False)
    description = Column(String,  nullable=False)
    features    = Column(JSON,    nullable=False)   


    monthly_price_id  = Column(Integer, ForeignKey("prices.id"), nullable=True)
    annual_price_id   = Column(Integer, ForeignKey("prices.id"), nullable=True)

    monthly_price = relationship("Price", foreign_keys=[monthly_price_id])
    annual_price  = relationship("Price", foreign_keys=[annual_price_id])