"""一键重灌脚本 - 按《精密五金工厂设备与产品》场景清理并重新生成全量数据

执行顺序：
1. 清理 PG 业务数据：work_orders / knowledge_items / spare_parts / devices（**保留用户账号**）
2. 清理 fault_code_mappings / categories(DEVICE_TYPE) / 故障现象级联 / 根本原因级联
3. 清理 Milvus 旧向量：knowledge 集合 + log_code 集合（无残留）
4. 依次运行种子脚本（每个脚本失败即终止）：
   seed_data.py                         → 设备200 / 备件 / 工单200 / 知识50（PG）
   init_categories.py                   → 设备类型 8 类（PG）
   seed_categories.py                   → 故障现象/根本原因级联（PG）
   seed_fault_codes.py                  → 故障码映射 104 条（PG）
   import_manual_codes.py --force-rebuild → 手册错误码 100 条（PG + Milvus log_code）
   sync_vectors.py                      → 知识 PG → Milvus knowledge
5. 核对 PG / Milvus 计数 + 有日志 83% 占比

前提条件：
    PostgreSQL(15432) / Milvus(19530) / Redis(7379) / 推理服务(8010) 均已启动
    （start_all.ps1 或各服务分别启动）

使用方式:
    cd backend
    python scripts/reseed_precision_hardware.py
"""
import os
import subprocess
import sys

# Windows 控制台默认 GBK 无法编码 ✅/❌ 等字符，统一改为 UTF-8 输出（含子进程）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.vector_store import vector_store, log_code_store, VectorStore, LogCodeVectorStore


def clear_pg():
    """清理 PG 业务数据（保留 users），按外键约束逆序"""
    db = SessionLocal()
    try:
        print("\n[1/4] 清理 PostgreSQL 业务数据（保留用户）...")
        # 业务表（work_orders 引用 devices，需先删工单）
        db.execute(text("DELETE FROM work_orders"))
        db.execute(text("DELETE FROM knowledge_items"))
        db.execute(text("DELETE FROM spare_parts"))
        db.execute(text("DELETE FROM devices"))
        # 分类 / 映射表
        db.execute(text("DELETE FROM fault_code_mappings"))
        db.execute(text("DELETE FROM categories WHERE category_type = 'DEVICE_TYPE'"))
        db.execute(text("DELETE FROM fault_phenomenon_categories"))
        db.execute(text("DELETE FROM root_cause_categories"))
        db.commit()
        print("  已清空：work_orders / knowledge_items / spare_parts / devices")
        print("         fault_code_mappings / categories(DEVICE_TYPE) / 故障现象级联 / 根本原因级联")
        print("  保留：users（现有用户账号）")
    except Exception as e:
        db.rollback()
        print(f"❌ PG 清理失败: {e}")
        raise
    finally:
        db.close()


def clear_milvus():
    """清理 Milvus 旧向量（knowledge + log_code 集合）"""
    print("\n[2/4] 清理 Milvus 旧向量...")
    for name, store in (("knowledge", vector_store), ("log_code", log_code_store)):
        try:
            store.drop_collection()
            print(f"  已删除 Milvus 集合: {name}")
        except Exception as e:
            print(f"  ⚠️ {name} 集合清理失败: {e}（若 Milvus 未启动，后续脚本会报错）")
    print("  旧向量已清除，后续脚本将按新 schema 自动重建集合")


def run_scripts():
    """依次运行种子脚本，任一失败立即终止"""
    scripts = [
        ("seed_data.py", []),
        ("init_categories.py", []),
        ("seed_categories.py", []),
        ("seed_fault_codes.py", []),
        ("import_manual_codes.py", ["--force-rebuild"]),
        ("sync_vectors.py", []),
    ]
    print("\n[3/4] 依次执行种子脚本...")
    env = dict(os.environ)
    env["PYTHONPATH"] = BACKEND_DIR + os.pathsep + env.get("PYTHONPATH", "")

    for i, (name, args) in enumerate(scripts, 1):
        path = os.path.join(BACKEND_DIR, "scripts", name)
        argv = " ".join(args)
        print(f"\n--- [{i}/{len(scripts)}] python scripts/{name} {argv} ---")
        result = subprocess.run(
            [sys.executable, path, *args],
            cwd=BACKEND_DIR,
            env=env,
        )
        if result.returncode != 0:
            print(f"\n❌ 脚本 {name} 执行失败（返回码 {result.returncode}），重灌终止。")
            sys.exit(result.returncode)
    print("\n[3/4] 全部种子脚本执行完成")


def verify():
    """核对 PG / Milvus 计数与有日志占比"""
    print("\n[4/4] 核对数据计数...")
    db = SessionLocal()
    try:
        labels = [
            ("devices（设备）", "SELECT count(*) FROM devices"),
            ("work_orders（工单）", "SELECT count(*) FROM work_orders"),
            ("knowledge_items（知识）", "SELECT count(*) FROM knowledge_items"),
            ("manual_code_entries（手册码）", "SELECT count(*) FROM manual_code_entries"),
            ("fault_code_mappings（故障码映射）", "SELECT count(*) FROM fault_code_mappings"),
            ("fault_phenomenon_categories（现象级联）", "SELECT count(*) FROM fault_phenomenon_categories"),
            ("root_cause_categories（原因级联）", "SELECT count(*) FROM root_cause_categories"),
            ("spare_parts（备件）", "SELECT count(*) FROM spare_parts"),
            ("users（保留）", "SELECT count(*) FROM users"),
        ]
        for label, sql in labels:
            print(f"  {label:<32} {db.execute(text(sql)).scalar()}")

        total = db.execute(text("SELECT count(*) FROM devices")).scalar() or 0
        n_log = db.execute(
            text("SELECT count(*) FROM devices WHERE monitor_extra->>'has_log' = 'true'")
        ).scalar() or 0
        n_no_log = total - n_log
        if total:
            print(f"\n  有日志设备: {n_log} 台 = {n_log * 100 / total:.0f}%")
            print(f"  无日志设备: {n_no_log} 台 = {n_no_log * 100 / total:.0f}%")
            print(f"  （目标：有日志 83% / 无日志 17%）")
    finally:
        db.close()

    # Milvus 计数：用全新实例（清空重灌后旧单例的 Collection 句柄已失效）
    try:
        n_knowledge = VectorStore().count()
        n_log_code = LogCodeVectorStore().count()
        print(f"\n  Milvus knowledge 向量: {n_knowledge}（目标 50）")
        print(f"  Milvus log_code 向量: {n_log_code}（目标 100）")
    except Exception as e:
        print(f"  ⚠️ Milvus 计数失败（请确认 Milvus 已启动）: {e}")


def main():
    print("=" * 60)
    print("精密五金工厂场景 - 数据清理与重灌")
    print("=" * 60)
    clear_pg()
    clear_milvus()
    run_scripts()
    verify()
    print("\n" + "=" * 60)
    print("✅ 重灌完成！")
    print("=" * 60)
    print("\n后续建议（可选）：")
    print("  - 重启后端后做智能问答回归：python -m uvicorn app.main:app --port 18080")
    print("  - 重跑阈值标定：python scripts/calibrate_thresholds.py")


if __name__ == "__main__":
    main()
