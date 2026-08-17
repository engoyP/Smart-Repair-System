"""统一清理脚本 - 清空所有业务数据（保留用户账号）

清空范围：
  1. Milvus: knowledge + log_code 两个集合（drop_collection 后由 seed 脚本自动重建）
  2. PostgreSQL: 所有业务表（按外键约束逆序 DELETE），保留 users 表
  3. 重置所有 SERIAL/IDENTITY 序列，避免 ID 冲突

使用方式:
    cd backend
    python scripts/clean_all_data.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from loguru import logger

from app.core.database import SessionLocal
from app.core.config import settings


# ==================== 待清理表（按外键依赖逆序） ====================
# 保留 users 表，不做用户重建
TABLES_TO_CLEAN = [
    # 子表先删（有外键依赖）
    "work_order_progress_logs",   # progress_log.py
    "notifications",
    "work_order_import_items",     # work_order_import.py 子表
    "work_order_import_batches",   # work_order_import.py 主表
    "leave_requests_details",      # leave_request.py 子表
    "work_orders",                 # 引用 devices + users
    "knowledge_items",             # 引用 devices（间接）
    "spare_parts",
    "manual_code_entries",         # 手册错误码表
    "devices",
    "fault_code_mappings",
    "fault_phenomenon_categories",
    "root_cause_categories",
    "leave_requests",
    "duty_schedules",
    "categories",                  # 分类表（DEVICE_TYPE/FAULT_TYPE/KNOWLEDGE_TYPE）
    "sys_configs",                 # 系统配置表
]

# 对应的序列名（用于 RESTART IDENTITY）
# PostgreSQL 用 ALTER SEQUENCE ... RESTART WITH 1 重置序列
SEQUENCES_TO_RESET = [
    "devices_id_seq",
    "work_orders_id_seq",
    "knowledge_items_id_seq",
    "spare_parts_id_seq",
    "fault_code_mappings_id_seq",
    "categories_id_seq",
    "manual_code_entries_id_seq",
    "work_order_import_batches_id_seq",
    "work_order_import_items_id_seq",
    "work_order_progress_logs_id_seq",
    "notifications_id_seq",
    "duty_schedules_id_seq",
    "leave_requests_id_seq",
    "leave_requests_details_id_seq",
    "fault_phenomenon_categories_id_seq",
    "root_cause_categories_id_seq",
    "sys_configs_id_seq",
]


def clean_milvus():
    """清空 Milvus 向量库（drop 两个集合，后续 seed 脚本会自动重建）"""
    logger.info("开始清理 Milvus 向量库...")

    # knowledge 集合
    try:
        from app.core.vector_store import vector_store
        vector_store.drop_collection()
        logger.info(f"  已删除 Milvus 集合: {settings.MILVUS_COLLECTION}")
    except Exception as e:
        logger.warning(f"  删除集合 {settings.MILVUS_COLLECTION} 失败（可能不存在）: {e}")

    # log_code 集合
    try:
        from app.core.vector_store import log_code_store
        log_code_store.drop_collection()
        logger.info(f"  已删除 Milvus 集合: {settings.MILVUS_LOG_CODE_COLLECTION}")
    except Exception as e:
        logger.warning(f"  删除集合 {settings.MILVUS_LOG_CODE_COLLECTION} 失败（可能不存在）: {e}")

    logger.info("Milvus 清理完成")


def clean_postgresql():
    """清空 PostgreSQL 业务数据表（保留 users）"""
    db = SessionLocal()
    try:
        logger.info("开始清理 PostgreSQL 业务数据...")

        # 临时禁用外键约束检查（PostgreSQL 用 session_replication_role）
        db.execute(text("SET session_replication_role = 'replica'"))

        total_deleted = 0
        for table in TABLES_TO_CLEAN:
            try:
                result = db.execute(text(f"DELETE FROM {table}"))
                rows = result.rowcount
                total_deleted += rows
                if rows > 0:
                    logger.info(f"  {table}: 删除 {rows} 行")
            except Exception as e:
                # 表可能不存在（未迁移），跳过
                logger.warning(f"  {table}: 跳过（{e.__class__.__name__}: {str(e)[:80]}）")

        # 恢复外键约束检查
        db.execute(text("SET session_replication_role = 'origin'"))

        # 重置序列
        logger.info("重置自增序列...")
        for seq in SEQUENCES_TO_RESET:
            try:
                db.execute(text(f"ALTER SEQUENCE IF EXISTS {seq} RESTART WITH 1"))
            except Exception as e:
                logger.warning(f"  {seq}: 跳过（{str(e)[:60]}）")

        db.commit()
        logger.info(f"PostgreSQL 清理完成，共删除 {total_deleted} 行业务数据（users 表保留）")

    except Exception as e:
        db.rollback()
        logger.error(f"清理失败: {e}")
        raise
    finally:
        db.close()


def clean_redis():
    """清空 Redis 缓存中的会话/检索缓存（可选，不影响数据完整性）"""
    try:
        import redis
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
        )
        r.ping()
        # 只删除知识检索相关的缓存键，不删除全部（避免影响在线会话）
        patterns = ["knowledge:*", "search:*", "dedup:*", "session:*"]
        deleted = 0
        for pattern in patterns:
            for key in r.scan_iter(match=pattern, count=100):
                r.delete(key)
                deleted += 1
        if deleted > 0:
            logger.info(f"  Redis: 清除 {deleted} 个缓存键（knowledge/search/dedup/session）")
        else:
            logger.info("  Redis: 无相关缓存键")
    except Exception as e:
        logger.warning(f"  Redis 清理跳过（{e.__class__.__name__}）")


def main():
    print("=" * 60)
    print("  Smart-Repair-System 数据清理")
    print("  保留：users 表（用户账号）")
    print("  清空：设备/工单/知识/备件/分类/故障码/排班/通知等全部业务数据")
    print("  清空：Milvus 向量库（knowledge + log_code 集合）")
    print("=" * 60)

    # 1. Milvus
    clean_milvus()

    # 2. PostgreSQL
    clean_postgresql()

    # 3. Redis 缓存
    clean_redis()

    print()
    print("=" * 60)
    print("  清理完成！users 表已保留，可执行 reseed_all.py 重新生成数据")
    print("=" * 60)


if __name__ == "__main__":
    main()
