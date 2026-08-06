"""历史工单 PDF 批量导入：批次表 + 抽取结果草稿表

流程：
1. 上传 PDF → 跑 LangGraph 导入工作流（解析→抽取→校验）→ 写入 WorkOrderImportItem（PENDING）
2. 后台人工确认/修改/拒绝
3. 确认后写入 work_orders，并同步收录知识库（人工确认之后才去重收录）
"""
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class WorkOrderImportBatch(BaseModel):
    __tablename__ = "work_order_import_batches"

    batch_no = Column(String(50), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PROCESSING",
                    comment="PROCESSING / DONE / PARTIAL")
    file_count = Column(Integer, nullable=False, default=0)
    total_count = Column(Integer, nullable=False, default=0, comment="抽取成功进入待确认数")
    success_count = Column(Integer, nullable=False, default=0, comment="确认入库数")
    failed_count = Column(Integer, nullable=False, default=0, comment="解析/抽取失败数")
    report = Column(JSONB, nullable=True, comment="每份 PDF 的处理结果摘要")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    items = relationship("WorkOrderImportItem", back_populates="batch",
                         cascade="all, delete-orphan", order_by="WorkOrderImportItem.id")


class WorkOrderImportItem(BaseModel):
    __tablename__ = "work_order_import_items"

    batch_id = Column(Integer, ForeignKey("work_order_import_batches.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="PENDING",
                    comment="PENDING(待确认) / CONFIRMED(已入库) / REJECTED(已拒绝) / ERROR(解析失败)")
    error_message = Column(Text, nullable=True, comment="解析/抽取失败原因")
    extracted_text = Column(Text, nullable=True, comment="PDF 提取的原始文本（供人工核对）")
    extracted_data = Column(JSONB, nullable=True, comment="LLM 抽取的系统工单字段（待人工确认）")
    validate_warnings = Column(JSONB, nullable=True, comment="校验警告（设备/维修员/工单号等）")
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True,
                           comment="确认后生成的工单 id")
    confirmed_at = Column(TIMESTAMP, nullable=True)
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    batch = relationship("WorkOrderImportBatch", back_populates="items")
    work_order = relationship("WorkOrder")

    __table_args__ = (
        Index("ix_woi_batch_status", "batch_id", "status"),
    )
