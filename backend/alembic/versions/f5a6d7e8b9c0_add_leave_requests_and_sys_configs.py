"""add leave_requests, leave_requests_details, sys_configs tables
extend duty_schedules with source_leave_request_id + related fields

Revision ID: f5a6d7e8b9c0
Revises: e3f4d5c6b7a8
Create Date: 2026-08-03 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f5a6d7e8b9c0'
down_revision: Union[str, None] = 'e3f4d5c6b7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ------------------------------------------------------------------
# 请假类型枚举（和 LeaveType enum 对齐，PostgreSQL 原生 enum 可选）
# 这里用 VARCHAR + CHECK 约束，避免枚举值变更时要 DROP TYPE
# ------------------------------------------------------------------


def upgrade() -> None:
    # ---------- 1. sys_configs ----------
    op.create_table(
        "sys_configs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sys_configs_key", "sys_configs", ["key"], unique=True)

    # 种子：min_guard_count = 2
    op.execute(
        sa.text(
            """
            INSERT INTO sys_configs (key, value, description, created_at, updated_at)
            VALUES (:k, :v, :d, NOW(), NOW())
            ON CONFLICT (key) DO NOTHING
            """
        ).bindparams(
            k="min_guard_count",
            v="2",
            d="请假审批后最低值班人数；低于此值时主管必须指定顶岗人才能批准",
        )
    )
    # 种子：leave_pending_timeout_hours = 4（超时加急催办）
    op.execute(
        sa.text(
            """
            INSERT INTO sys_configs (key, value, description, created_at, updated_at)
            VALUES (:k, :v, :d, NOW(), NOW())
            ON CONFLICT (key) DO NOTHING
            """
        ).bindparams(
            k="leave_pending_timeout_hours",
            v="4",
            d="请假待审批超过该小时数，自动加急 @ 主管催办",
        )
    )

    # ---------- 2. leave_requests ----------
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("requester_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requester_name", sa.String(100), nullable=False),
        sa.Column("leave_type", sa.String(30), nullable=False, server_default="ANNUAL"),
        sa.Column("leave_reason", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("approver_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approver_comment", sa.Text, nullable=True),
        sa.Column("substitute_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("handled_at", sa.TIMESTAMP(timezone=False), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_leave_requests_requester_id", "leave_requests", ["requester_id"])
    op.create_index("ix_leave_requests_status", "leave_requests", ["status"])
    op.create_index("ix_leave_requests_correlation_id", "leave_requests", ["correlation_id"], unique=True)

    # ---------- 3. leave_requests_details ----------
    op.create_table(
        "leave_requests_details",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("leave_request_id", sa.Integer, sa.ForeignKey("leave_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("leave_date", sa.Date, nullable=False),
        sa.Column("leave_shift", sa.String(20), nullable=False, server_default="ALL_DAY"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("leave_request_id", "leave_date", "leave_shift", name="uq_leave_req_day_shift"),
    )
    op.create_index("ix_lrd_date_shift", "leave_requests_details", ["leave_date", "leave_shift"])

    # ---------- 4. duty_schedules 扩展字段 ----------
    # source_leave_request_id + source_substitute_for_id
    op.add_column(
        "duty_schedules",
        sa.Column("source_leave_request_id", sa.Integer,
                  sa.ForeignKey("leave_requests.id", ondelete="SET NULL"), nullable=True,
                  comment="生成该排班的请假申请ID（LEAVE 类型）"),
    )
    op.add_column(
        "duty_schedules",
        sa.Column("source_substitute_for_id", sa.Integer, nullable=True,
                  comment="顶岗排班时，对应顶替的请假申请ID（SUBSTITUTE 类型）"),
    )
    # 更新 schedule_type comment 追加 SUBSTITUTE（实际列的 server_default 不变）
    # （SQLAlchemy comment 仅文档用途，这里不需要 ALTER 列定义）


def downgrade() -> None:
    op.drop_column("duty_schedules", "source_substitute_for_id")
    op.drop_column("duty_schedules", "source_leave_request_id")
    op.drop_index("ix_lrd_date_shift", table_name="leave_requests_details")
    op.drop_table("leave_requests_details")
    op.drop_index("ix_leave_requests_correlation_id", table_name="leave_requests")
    op.drop_index("ix_leave_requests_status", table_name="leave_requests")
    op.drop_index("ix_leave_requests_requester_id", table_name="leave_requests")
    op.drop_table("leave_requests")
    op.drop_index("ix_sys_configs_key", table_name="sys_configs")
    op.drop_table("sys_configs")
