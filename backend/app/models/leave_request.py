"""请假申请单 + 按天拆单明细

Phase 2.1 新增：
- leave_requests        请假申请主表（含 correlation_id 幂等、substitute_user_id 顶岗人、审批信息）
- leave_requests_details 按天拆单明细（每条对应「某一天 + 某一班次」的请假单元）
- duty_schedules.source_leave_request_id 反向外键，便于从排班追溯到哪条请假申请生成的
"""
import enum
from sqlalchemy import Column, Integer, String, Date, TIMESTAMP, ForeignKey, Text, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from datetime import datetime


class LeaveType(str, enum.Enum):
    ANNUAL = "ANNUAL"               # 年假
    SICK = "SICK"                   # 病假
    PERSONAL = "PERSONAL"           # 事假
    COMPENSATION = "COMPENSATION"   # 调休
    MARRIAGE = "MARRIAGE"           # 婚假
    MATERNITY = "MATERNITY"         # 产假
    FUNERAL = "FUNERAL"             # 丧假
    OTHER = "OTHER"                 # 其他


class LeaveRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class LeaveShift(str, enum.Enum):
    ALL_DAY = "ALL_DAY"
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"


class LeaveRequest(BaseModel):
    __tablename__ = "leave_requests"

    requester_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
                          comment="申请人 user_id（维修师傅）")
    requester_name = Column(String(100), nullable=False, comment="冗余姓名，卡片展示用")

    leave_type = Column(String(30), nullable=False, default=LeaveType.ANNUAL.value,
                        comment="假别：ANNUAL/SICK/PERSONAL/COMPENSATION/MARRIAGE/MATERNITY/FUNERAL/OTHER")
    leave_reason = Column(Text, nullable=True, comment="请假理由（师傅填）")

    status = Column(String(20), nullable=False, default=LeaveRequestStatus.PENDING.value, index=True,
                    comment="PENDING / APPROVED / REJECTED / CANCELLED")

    approver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                         comment="审批人（主管）user_id")
    approver_comment = Column(Text, nullable=True,
                              comment="拒绝必填理由 / 同意备注")

    substitute_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                comment="人数不足时主管强制指定的顶岗人 user_id，生成排班时用")

    correlation_id = Column(String(100), nullable=False, unique=True, index=True,
                            comment="钉钉 outTrackId / processInstanceId，唯一索引做幂等，防钉钉重试重复提交")

    submitted_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow, comment="师傅提交时间")
    handled_at = Column(TIMESTAMP, nullable=True, comment="主管审批/拒绝时间")

    requester = relationship("User", foreign_keys=[requester_id])
    approver = relationship("User", foreign_keys=[approver_id])
    substitute = relationship("User", foreign_keys=[substitute_user_id])
    details = relationship("LeaveRequestDetail", back_populates="leave_request",
                           cascade="all, delete-orphan", lazy="joined")


class LeaveRequestDetail(BaseModel):
    """按天拆的请假明细；审批通过后每条 detail 插入一条 LEAVE 类型的 duty_schedules"""
    __tablename__ = "leave_requests_details"

    leave_request_id = Column(Integer, ForeignKey("leave_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_date = Column(Date, nullable=False, index=True, comment="具体某一天")
    leave_shift = Column(String(20), nullable=False, default=LeaveShift.ALL_DAY.value,
                         comment="ALL_DAY / MORNING / AFTERNOON")

    leave_request = relationship("LeaveRequest", back_populates="details")

    __table_args__ = (
        UniqueConstraint("leave_request_id", "leave_date", "leave_shift", name="uq_leave_req_day_shift"),
        Index("ix_lrd_date_shift", "leave_date", "leave_shift"),
    )
