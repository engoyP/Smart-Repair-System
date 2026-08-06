"""故障码映射表 - 故障码与故障名称一一对应"""
from sqlalchemy import Column, String, Text
from app.models.base import BaseModel


class FaultCodeMapping(BaseModel):
    __tablename__ = "fault_code_mappings"

    fault_code = Column(String(100), unique=True, nullable=False, index=True, comment="故障码")
    fault_description = Column(Text, nullable=False, comment="故障描述/现象")
    device_type = Column(String(100), comment="设备类型（可选）")
    source = Column(String(20), default="system", comment="来源: system(工单自动生成)/seed(种子数据)/manual(手动)")

    def __repr__(self):
        return f"<FaultCodeMapping(fault_code='{self.fault_code}')>"
