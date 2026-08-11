from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base
from app.core.config import settings

# 导入所有模型，确保 Base.metadata 能检测到表
from app.models.device import Device  # noqa: F401
from app.models.work_order import WorkOrder  # noqa: F401
from app.models.knowledge import KnowledgeItem  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.spare_part import SparePart  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.work_order_import import WorkOrderImportBatch, WorkOrderImportItem  # noqa: F401
from app.models.manual_code import ManualCodeEntry  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()