from sqlalchemy import Column, String, Text, Boolean, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class Notification(BaseModel):
    """站内通知"""
    # 注意：BaseModel 的 __tablename__ 会自动生成 "notifications"

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(50), nullable=False, default="work_order")  # work_order / system
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    work_order_id = Column(Integer, nullable=True, index=True)  # 关联工单（可选）
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    extra = Column(Text, nullable=True)  # JSON 字符串，存额外数据
