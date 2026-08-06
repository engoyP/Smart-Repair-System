"""add_progress_logs_duty_schedules_users_ext

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-07-31 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ENUM as PgEnum


revision: str = 'd2b3c4e5f6a7'
down_revision: Union[str, None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 1. users 表扩展列 ===
    op.add_column('users', sa.Column('skills_json', JSONB, nullable=True,
                                     comment='技能熟练度字典 {类型:1-5}'))
    op.add_column('users', sa.Column('current_workload_count', sa.Integer, server_default='0',
                                     nullable=False, comment='当前未完成工单数(冗余)'))
    op.add_column('users', sa.Column('last_online_at', sa.TIMESTAMP(timezone=False), nullable=True,
                                     comment='最近在线时间'))
    # 旧 skills 列数据迁移：逗号分隔 → JSONB 每项默认熟练 3
    op.execute(sa.text("""
        UPDATE users
           SET skills_json = (
               SELECT jsonb_object_agg(trim(k), 3)
                 FROM unnest(string_to_array(skills, ',')) AS k
                WHERE skills IS NOT NULL AND length(trim(skills)) > 0
           )
         WHERE skills_json IS NULL
    """))

    # 复用已存在的 workorderstatus 类型，不再重复创建
    WOStatus = PgEnum(
        'PENDING', 'ASSIGNED', 'ACCEPTED', 'ARRIVED',
        'INSPECTING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED',
        name='workorderstatus', create_type=False,
    )

    # === 2. 维修进度日志表 ===
    op.create_table(
        'work_order_progress_logs',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('work_order_id', sa.Integer,
                  sa.ForeignKey('work_orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('from_status', WOStatus, nullable=True),
        sa.Column('to_status', WOStatus, nullable=False),
        sa.Column('operator_id', sa.Integer,
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('operator_name', sa.String(100), nullable=True),
        sa.Column('source', sa.String(30), nullable=False, server_default='WEB',
                  comment='WEB / MOBILE / DINGTALK_CARD / SYSTEM'),
        sa.Column('remark', sa.Text, nullable=True),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('attachments', JSONB, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=False),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_progress_logs_woid_created', 'work_order_progress_logs',
                    ['work_order_id', 'created_at'])

    # === 3. 排班值日表 ===
    op.create_table(
        'duty_schedules',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('date', sa.Date, nullable=False, index=True),
        sa.Column('shift', sa.String(20), nullable=False, server_default='MORNING',
                  comment='MORNING / AFTERNOON / NIGHT'),
        sa.Column('user_id', sa.Integer,
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('schedule_type', sa.String(30), nullable=False, server_default='MANUAL',
                  comment='WEEKLY_ROUTINE / MANUAL'),
        sa.Column('note', sa.String(200), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=False),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_duty_date_shift', 'duty_schedules', ['date', 'shift'])


def downgrade() -> None:
    op.drop_index('ix_duty_date_shift', table_name='duty_schedules')
    op.drop_table('duty_schedules')
    op.drop_index('ix_progress_logs_woid_created', table_name='work_order_progress_logs')
    op.drop_table('work_order_progress_logs')
    op.drop_column('users', 'last_online_at')
    op.drop_column('users', 'current_workload_count')
    op.drop_column('users', 'skills_json')
