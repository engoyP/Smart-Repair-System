from sqlalchemy import Column, String, Text, Integer, Float, TIMESTAMP, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
import enum
from datetime import datetime


class WorkOrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    ARRIVED = "ARRIVED"
    INSPECTING = "INSPECTING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ARCHIVING = "ARCHIVING"  # 维修完成，待归档（网页补充表单后归档）
    REJECTED = "REJECTED"
    # 保留旧状态兼容已有数据
    STANDARDIZED = "STANDARDIZED"
    CLASSIFIED = "CLASSIFIED"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"


class WorkOrder(BaseModel):
    __tablename__ = "work_orders"

    work_order_no = Column(String(50), unique=True, nullable=False, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    device_code = Column(String(50))  # 扫码获取的设备编码
    fault_code = Column(Text, comment="故障码，多个用逗号分隔")
    device_error_code = Column(String(200), comment="设备运行日志/屏幕报警的错误码（如 SV0436 / 6401），仅带错误码的机电设备填，多个用逗号分隔")
    fault_description = Column(Text, nullable=False)
    fault_category = Column(String(100), comment="故障大类")
    fault_phenomenon_type = Column(String(200), comment="故障具体现象（级联二级）")
    fault_phenomenon = Column(Text, comment="故障现象补充描述")
    fault_media = Column(JSONB, comment="移动端上报的图片/语音文件URL列表")
    attachments = Column(JSONB, comment="附件列表 [{url, name, type}]")
    root_cause_category = Column(String(100), comment="根本原因大类")
    root_cause_type = Column(String(200), comment="根本原因具体类型（级联二级）")
    root_cause = Column(Text, comment="根本原因补充说明")
    solution_steps = Column(Text)
    solution_ref_knowledge_id = Column(Integer, comment="引用的知识条目ID")
    repair_result = Column(String(20), comment="维修结果: PERMANENT_FIX / TEMPORARY_FIX / UNABLE_FIX")
    follow_up_plan = Column(Text, comment="临时措施后续计划")
    work_hours = Column(Float, comment="工时（小时）")
    used_parts = Column(JSONB)
    start_time = Column(TIMESTAMP)
    end_time = Column(TIMESTAMP)
    technician_id = Column(Integer, ForeignKey("users.id"), comment="指派的维修人员 ID")
    assignee_id = Column(Integer, ForeignKey("users.id"), comment="当前处理人 ID")
    reporter_id = Column(Integer, ForeignKey("users.id"), comment="上报人员 ID（移动端提交）")
    priority = Column(String(10), default="MEDIUM", comment="优先级: LOW/MEDIUM/HIGH/CRITICAL")
    location = Column(String(200), comment="故障设备位置")
    status = Column(SQLEnum(WorkOrderStatus), default=WorkOrderStatus.DRAFT, nullable=False)
    tags = Column(JSONB)
    confidence = Column(Float, nullable=True, comment="AI 分析置信度 (0-1)")
    analysis_result = Column(JSONB, nullable=True, comment="AI 分析结果完整记录")
    dispatch_score = Column(JSONB, nullable=True, comment="派工评分详情")
    completion_report = Column(JSONB, nullable=True, comment="维修完成报告（工时/备件/照片）")
    created_by = Column(Integer, ForeignKey("users.id"), comment="创建者 ID，仅创建者可编辑")

    device = relationship("Device", back_populates="work_orders")
    technician = relationship("User", foreign_keys=[technician_id], lazy="joined")
    progress_logs = relationship(
        "WorkOrderProgressLog", back_populates="work_order",
        order_by="WorkOrderProgressLog.created_at.asc()",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<WorkOrder(work_order_no='{self.work_order_no}', status='{self.status}')>"