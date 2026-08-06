"""drop_device_health_score

Revision ID: 59fa4817b5b4
Revises: 2a5022bf6eca
Create Date: 2026-07-31 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '59fa4817b5b4'
down_revision: Union[str, None] = '2a5022bf6eca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('devices', 'health_score')


def downgrade() -> None:
    op.add_column('devices', sa.Column('health_score', sa.Integer(), nullable=True, comment='健康度 0-100'))
