"""故障现象级联分类表"""
from sqlalchemy import Column, String, Integer, Text
from app.models.base import BaseModel


class FaultPhenomenonCategory(BaseModel):
    __tablename__ = "fault_phenomenon_categories"

    parent_id = Column(Integer, nullable=True, comment="父级ID，NULL=大类")
    name = Column(String(200), nullable=False, comment="分类名称")
    device_type = Column(String(100), comment="关联设备类型，NULL=通用")
    description = Column(Text, comment="分类描述")
    sort_order = Column(Integer, default=0, comment="排序")
