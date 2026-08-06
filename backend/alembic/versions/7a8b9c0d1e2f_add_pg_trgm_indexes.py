"""add pg_trgm gin indexes for knowledge bm25 search

Revision ID: 7a8b9c0d1e2f
Revises: f6bfd2334868
Create Date: 2026-08-05 20:10:00.000000

为 knowledge_items.title / content 添加 pg_trgm GIN 索引，
加速 BM25 检索的 ILIKE '%关键词%' 模糊匹配（上千条数据后避免全表扫描）。
"""
from typing import Sequence, Union

from alembic import op


revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, None] = 'f6bfd2334868'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_trgm 是 PostgreSQL 13+ 的 trusted extension，普通库用户即可创建
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_title_trgm "
        "ON knowledge_items USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_content_trgm "
        "ON knowledge_items USING gin (content gin_trgm_ops)"
    )


def downgrade() -> None:
    # 只回滚本 migration 创建的索引，extension 保留（可能被其他地方依赖）
    op.execute("DROP INDEX IF EXISTS idx_knowledge_content_trgm")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_title_trgm")
