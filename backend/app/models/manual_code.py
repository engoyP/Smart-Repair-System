"""设备手册错误码条目 - 从设备说明书导入的"错误码 → 故障诊断"权威映射

与知识库（KnowledgeItem，工单沉淀）职责分离：
- 知识库（knowledge_items） = 历史维修工单案例（真实发生过的故障与处理），
  涉及错误码的工单照常沉淀到这里（错误码提取进 fault_code 字段）
- 手册表（manual_code_entries） = 设备说明书/维修手册中的错误码表（权威静态映射），
  只允许通过说明书导入，含章节/页码用于出处回溯
"""
from sqlalchemy import Column, String, Text, Integer
from app.models.base import BaseModel


class ManualCodeEntry(BaseModel):
    __tablename__ = "manual_code_entries"

    milvus_id = Column(String(100), unique=True, index=True, comment="Milvus 向量 ID")
    manual_name = Column(String(200), nullable=False, comment="设备说明书/手册名称，如 KUKA KR210 维修手册")
    device_type = Column(String(100), comment="设备类型（机械臂/数控机床等）")
    error_code = Column(String(100), index=True, nullable=False, comment="错误码/报警码，如 SV0436 / ALM-6401")
    title = Column(String(300), nullable=False, comment="错误码标题（如：主轴过流）")
    description = Column(Text, nullable=False, comment="错误含义/触发条件（说明书原文）")
    causes = Column(Text, comment="可能原因（说明书原文）")
    solutions = Column(Text, comment="处理步骤/排查方向（说明书原文）")
    chapter = Column(String(200), comment="所属章节（出处回溯）")
    page = Column(String(50), comment="页码（出处回溯）")
    version = Column(Integer, default=1, comment="条目版本")

    def __repr__(self):
        return f"<ManualCodeEntry(id={self.id}, error_code='{self.error_code}', title='{self.title}')>"
