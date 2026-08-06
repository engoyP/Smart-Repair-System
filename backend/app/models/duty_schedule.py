from sqlalchemy import Column, Integer, String, Date, TIMESTAMP, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
import enum


class ShiftType(str, enum.Enum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    NIGHT = "NIGHT"


class DutySchedule(BaseModel):
    __tablename__ = "duty_schedules"

    date = Column(Date, nullable=False, index=True)
    shift = Column(String(20), nullable=False, server_default=ShiftType.MORNING.value)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_type = Column(String(30), nullable=False, server_default="MANUAL",
                           comment="WEEKLY_ROUTINE / MANUAL / LEAVE / SUBSTITUTE")
    note = Column(String(200), nullable=True)
    leave_type = Column(String(30), nullable=True)
    leave_status = Column(String(20), nullable=False, server_default='APPROVED')
    source_leave_request_id = Column(Integer, ForeignKey("leave_requests.id", ondelete="SET NULL"), nullable=True,
                                     comment="生成这条排班记录的请假申请 ID；便于追溯/撤销")
    source_substitute_for_id = Column(Integer, nullable=True,
                                   comment="若 schedule_type=SUBSTITUTE 时，顶替的是哪个请假申请 id（冗余）")
    created_at = Column(TIMESTAMP, nullable=False, server_default="now()")

    user = relationship("User", back_populates="duty_schedules")
    source_leave_request = relationship("LeaveRequest", foreign_keys=[source_leave_request_id])

    __table_args__ = (
        Index("ix_duty_date_shift", "date", "shift"),
    )
