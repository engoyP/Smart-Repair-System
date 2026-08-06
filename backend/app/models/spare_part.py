from sqlalchemy import Column, String, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class SparePart(BaseModel):
    __tablename__ = "spare_parts"

    part_code = Column(String(50), unique=True, nullable=False, index=True)
    part_name = Column(String(200), nullable=False)
    specification = Column(String(200))
    unit = Column(String(20), default="个")
    stock_quantity = Column(Integer, default=0)
    safety_stock = Column(Integer, default=0)
    unit_price = Column(Float, default=0.0)
    device_type = Column(String(100))
    location = Column(String(200))
    supplier = Column(String(200))

    def __repr__(self):
        return f"<SparePart(part_code='{self.part_code}', part_name='{self.part_name}')>"