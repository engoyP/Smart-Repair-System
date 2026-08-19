from sqlalchemy import Column, String, Text, Integer, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import BaseModel
import enum


class KnowledgeStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class KnowledgeItem(BaseModel):
    __tablename__ = "knowledge_items"

    milvus_id = Column(String(100), unique=True, index=True)  # Milvus 向量 ID
    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    device_type = Column(String(100))
    fault_code = Column(Text, comment="故障码，多个用逗号分隔")
    fault_tags = Column(JSONB)
    source_type = Column(String(20))
    source_id = Column(Integer)
    status = Column(SQLEnum(KnowledgeStatus), default=KnowledgeStatus.DRAFT, nullable=False)
    version = Column(Integer, default=1)
    review_comment = Column(Text, nullable=True, comment="审核备注（驳回原因/修改建议）")
    extraction_meta = Column(JSONB, nullable=True, comment="提取元数据（去重分数/关联工单/关联知识等）")

    def __repr__(self):
        return f"<KnowledgeItem(id={self.id}, title='{self.title}', status='{self.status}')>"