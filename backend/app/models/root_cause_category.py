"""根本原因级联分类表"""
from sqlalchemy import Column, String, Integer, Text
from app.models.base import BaseModel


class RootCauseCategory(BaseModel):
    __tablename__ = "root_cause_categories"

    parent_id = Column(Integer, nullable=True, comment="父级ID，NULL=大类")
    name = Column(String(200), nullable=False, comment="分类名称")
    description = Column(Text, comment="分类描述")
    sort_order = Column(Integer, default=0, comment="排序")
