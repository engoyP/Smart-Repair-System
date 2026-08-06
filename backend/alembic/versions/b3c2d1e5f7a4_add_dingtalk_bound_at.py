"""add dingtalk_bound_at to users

Revision ID: b3c2d1e5f7a4
Revises: 59fa4817b5b4
Create Date: 2026-07-31 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "b3c2d1e5f7a4"
down_revision = "59fa4817b5b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("dingtalk_bound_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "dingtalk_bound_at")
