"""add_status_accepted_arrived_inspecting

Revision ID: c1a2b3d4e5f6
Revises: b3c2d1e5f7a4
Create Date: 2026-07-31 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b3c2d1e5f7a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # 新增 3 个状态值（幂等：if not exists 风格）
    new_values = ['ACCEPTED', 'ARRIVED', 'INSPECTING']
    for val in new_values:
        try:
            conn.execute(sa.text(f"ALTER TYPE workorderstatus ADD VALUE '{val}'"))
        except Exception:
            pass


def downgrade() -> None:
    # 从 enum 移除值通常无法直接操作（Postgres 限制），此处留空
    pass
