from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class Category(BaseModel):
    """分类树 — 用于设备类型、故障类型等层级分类"""
    __tablename__ = "categories"

    name = Column(String(100), nullable=False)
    code = Column(String(50), unique=True, nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_type = Column(String(30), nullable=False, index=True)  # DEVICE_TYPE / FAULT_TYPE / KNOWLEDGE_TYPE
    sort_order = Column(Integer, default=0)
    description = Column(String(500))

    parent = relationship("Category", remote_side="Category.id", backref="children")

    def __repr__(self):
        return f"<Category(code='{self.code}', name='{self.name}')>"