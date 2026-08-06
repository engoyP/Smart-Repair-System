"""add work_order_import tables

Revision ID: f6bfd2334868
Revises: a6b7c8d9e0f1
Create Date: 2026-08-05 11:21:46.719229

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6bfd2334868'
down_revision: Union[str, None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('work_order_import_batches',
    sa.Column('batch_no', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False, comment='PROCESSING / DONE / PARTIAL'),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('total_count', sa.Integer(), nullable=False, comment='抽取成功进入待确认数'),
    sa.Column('success_count', sa.Integer(), nullable=False, comment='确认入库数'),
    sa.Column('failed_count', sa.Integer(), nullable=False, comment='解析/抽取失败数'),
    sa.Column('report', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='每份 PDF 的处理结果摘要'),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_order_import_batches_batch_no'), 'work_order_import_batches', ['batch_no'], unique=True)
    op.create_index(op.f('ix_work_order_import_batches_id'), 'work_order_import_batches', ['id'], unique=False)
    op.create_table('work_order_import_items',
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False, comment='PENDING(待确认) / CONFIRMED(已入库) / REJECTED(已拒绝) / ERROR(解析失败)'),
    sa.Column('error_message', sa.Text(), nullable=True, comment='解析/抽取失败原因'),
    sa.Column('extracted_text', sa.Text(), nullable=True, comment='PDF 提取的原始文本（供人工核对）'),
    sa.Column('extracted_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='LLM 抽取的系统工单字段（待人工确认）'),
    sa.Column('validate_warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='校验警告（设备/维修员/工单号等）'),
    sa.Column('work_order_id', sa.Integer(), nullable=True, comment='确认后生成的工单 id'),
    sa.Column('confirmed_at', sa.TIMESTAMP(), nullable=True),
    sa.Column('confirmed_by', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['work_order_import_batches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['confirmed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_woi_batch_status', 'work_order_import_items', ['batch_id', 'status'], unique=False)
    op.create_index(op.f('ix_work_order_import_items_batch_id'), 'work_order_import_items', ['batch_id'], unique=False)
    op.create_index(op.f('ix_work_order_import_items_id'), 'work_order_import_items', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_work_order_import_items_id'), table_name='work_order_import_items')
    op.drop_index(op.f('ix_work_order_import_items_batch_id'), table_name='work_order_import_items')
    op.drop_index('ix_woi_batch_status', table_name='work_order_import_items')
    op.drop_table('work_order_import_items')
    op.drop_index(op.f('ix_work_order_import_batches_id'), table_name='work_order_import_batches')
    op.drop_index(op.f('ix_work_order_import_batches_batch_no'), table_name='work_order_import_batches')
    op.drop_table('work_order_import_batches')
