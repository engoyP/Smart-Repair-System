from sqlalchemy import Column, String, Boolean, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from datetime import datetime


class UserRole(str, __import__('enum').Enum):
    ADMIN = "ADMIN"
    TECHNICIAN = "TECHNICIAN"
    SUPERVISOR = "SUPERVISOR"
    WORKER = "WORKER"


class User(BaseModel):
    __tablename__ = "users"

    username = Column(String(50), unique=True, nullable=False, index=True)
    employee_id = Column(String(50), unique=True, nullable=True, index=True, comment="工号，唯一")
    password_hash = Column(String(255), nullable=False)
    real_name = Column(String(100), nullable=False)
    email = Column(String(200))
    phone = Column(String(20))
    role = Column(String(20), default=UserRole.TECHNICIAN.value, nullable=False)
    is_active = Column(Boolean, default=True)

    dingtalk_userid = Column(String(100), unique=True, index=True, nullable=True)
    dingtalk_name = Column(String(100), nullable=True, comment="钉钉账号昵称")
    dingtalk_union_id = Column(String(100), nullable=True, index=True, comment="钉钉 unionId（跨应用唯一，机器人识别用）")
    dingtalk_bound_at = Column(DateTime, nullable=True, comment="钉钉账号绑定时间")
    department = Column(String(200))
    title = Column(String(100))
    skills = Column(String(500), comment="旧:技能标签(逗号分隔),保留1个月")
    skills_json = Column(JSONB, comment="技能熟练度字典 {类型: 1-5}")
    current_workload_count = Column(Integer, nullable=False, default=0,
                                     server_default="0", comment="当前未完成工单数(冗余)")
    last_online_at = Column(DateTime, nullable=True, comment="最近在线时间")
    last_login_at = Column(DateTime)

    work_orders = relationship("WorkOrder", foreign_keys="WorkOrder.assignee_id")
    duty_schedules = relationship("DutySchedule", back_populates="user",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(username='{self.username}', role='{self.role}')>"