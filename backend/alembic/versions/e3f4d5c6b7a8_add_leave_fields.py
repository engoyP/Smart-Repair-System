"""add_leave_fields

Revision ID: e3f4d5c6b7a8
Revises: d2b3c4e5f6a7
Create Date: 2026-08-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f4d5c6b7a8'
down_revision: Union[str, None] = 'd2b3c4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('duty_schedules', sa.Column('leave_type', sa.String(30), nullable=True,
                                              comment='请假类型：ANNUAL/SICK/PERSONAL/COMPENSATION/OTHER，仅 schedule_type=LEAVE 时有效'))
    op.add_column('duty_schedules', sa.Column('leave_status', sa.String(20), nullable=False, server_default='APPROVED',
                                              comment='审批状态：PENDING/APPROVED/REJECTED/CANCELLED；Phase1 主管直接登记默认 APPROVED'))


def downgrade() -> None:
    op.drop_column('duty_schedules', 'leave_status')
    op.drop_column('duty_schedules', 'leave_type')
