from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, ENUM as PG_ENUM
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from app.models.work_order import WorkOrderStatus


class WorkOrderProgressLog(BaseModel):
    __tablename__ = "work_order_progress_logs"

    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    from_status = Column(PG_ENUM(WorkOrderStatus, name="workorderstatus"), nullable=True)
    to_status = Column(PG_ENUM(WorkOrderStatus, name="workorderstatus"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    operator_name = Column(String(100), nullable=True)
    source = Column(String(30), nullable=False, server_default="WEB",
                    comment="WEB / MOBILE / DINGTALK_CARD / SYSTEM")
    remark = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)
    attachments = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default="now()")

    work_order = relationship("WorkOrder", back_populates="progress_logs")
    operator = relationship("User", foreign_keys=[operator_id])

    __table_args__ = (
        Index("ix_progress_logs_woid_created", "work_order_id", "created_at"),
    )
