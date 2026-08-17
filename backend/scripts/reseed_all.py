"""统一重生成入口 - 按依赖顺序执行清理 + 全部 seed 脚本

执行顺序：
  1. clean_all_data.py     → 清空所有业务数据（保留 users）
  2. init_categories.py    → 分类表（DEVICE_TYPE/FAULT_TYPE/KNOWLEDGE_TYPE）
  3. seed_categories.py    → 故障现象分类 + 根本原因分类
  4. seed_fault_codes.py   → 故障码映射表（104 条）
  5. seed_data.py           → 设备(200台) + 备件 + 工单(200单) + 知识(50条从工单)
  6. seed_knowledge.py     → 独立知识库（56条，8类设备 × 7条）
  7. import_manual_codes.py → 设备手册错误码（100 条，PG + Milvus log_code）
  8. sync_vectors.py        → Milvus 向量同步（覆盖全部已发布知识）

前提条件：
  - Docker 中间件已启动（PostgreSQL + Redis + Milvus）
  - 推理服务已启动（http://localhost:8010/health 返回 ok）
  - 数据库已迁移（alembic upgrade head）

使用方式:
    cd backend
    python scripts/reseed_all.py
"""
import sys
import os
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 脚本目录
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
# 后端目录（CWD for subprocess）
BACKEND_DIR = os.path.dirname(SCRIPTS_DIR)
# 虚拟环境 Python
VENV_PYTHON = os.path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable

# 执行步骤定义：(脚本文件名, 描述, 是否必须成功)
STEPS = [
    ("clean_all_data.py",    "清理全部业务数据（保留 users）",          True),
    ("init_categories.py",   "分类表（设备类型/故障类型/知识类型）",      True),
    ("seed_categories.py",   "故障现象分类 + 根本原因分类",            True),
    ("seed_fault_codes.py",  "故障码映射表（104 条）",                 True),
    ("seed_data.py",         "设备(200台) + 备件 + 工单(200单) + 工单知识", True),
    ("seed_knowledge.py",   "独立知识库（56 条，8 类设备 × 7 条）",    True),
    ("import_manual_codes.py", "设备手册错误码（100 条，PG + log_code 向量）", True),
    ("sync_vectors.py",      "Milvus 向量同步",                       True),
]


def run_step(script_name, description, required=True):
    """执行单个 seed 脚本"""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"  [SKIP] {script_name} 不存在")
        return False

    print(f"\n{'─' * 60}")
    print(f"  执行: {script_name}")
    print(f"  描述: {description}")
    print(f"{'─' * 60}")

    start = time.time()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"  # 避免子进程在 GBK 控制台打印中文/emoji 报错
    result = subprocess.run(
        [PYTHON, script_path],
        cwd=BACKEND_DIR,
        capture_output=False,
        env=env,
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n  [FAIL] {script_name} 执行失败（退出码 {result.returncode}，耗时 {elapsed:.1f}s）")
        if required:
            print("  该步骤必须成功，终止后续执行。")
            return False
        else:
            print("  该步骤非必须，继续执行后续步骤。")
            return True
    else:
        print(f"\n  [OK] {script_name} 完成（耗时 {elapsed:.1f}s）")
        return True


def check_prerequisites():
    """检查前提条件：推理服务 + PostgreSQL + Milvus"""
    print("=" * 60)
    print("  Smart-Repair-System 数据重生成")
    print("=" * 60)
    print()

    # 检查推理服务
    print("[检查] 推理服务 (http://localhost:8010)...")
    try:
        from app.core.embeddings import is_server_available
        if is_server_available():
            print("  [OK] 推理服务就绪")
        else:
            print("  [FAIL] 推理服务不可用")
            print("  请先启动推理服务：start_all.ps1 或 python -m app.core.embedding_server")
            return False
    except Exception as e:
        print(f"  [WARN] 推理服务检查异常: {e}")
        print("  继续执行（向量相关步骤可能会失败）")

    # 检查 PostgreSQL
    print("[检查] PostgreSQL...")
    try:
        from app.core.database import SessionLocal
        db = SessionLocal()
        db.execute(__import__('sqlalchemy').text("SELECT 1"))
        db.close()
        print("  [OK] PostgreSQL 连接正常")
    except Exception as e:
        print(f"  [FAIL] PostgreSQL 连接失败: {e}")
        print("  请确认 Docker 中间件已启动：docker compose -f docker-compose.dev.yml up -d")
        return False

    # 检查 Milvus
    print("[检查] Milvus...")
    try:
        from app.core.config import settings
        from pymilvus import connections, utility
        connections.connect(
            alias="default",
            host=settings.MILVUS_HOST,
            port=str(settings.MILVUS_PORT),
        )
        print("  [OK] Milvus 连接正常")
    except Exception as e:
        print(f"  [FAIL] Milvus 连接失败: {e}")
        print("  请确认 Docker 中间件已启动：docker compose -f docker-compose.dev.yml up -d")
        return False

    return True


def main():
    if not check_prerequisites():
        print("\n前提条件检查未通过，请修复后重试。")
        sys.exit(1)

    print()
    print(f"将按顺序执行 {len(STEPS)} 个步骤：")
    for i, (script, desc, _) in enumerate(STEPS, 1):
        print(f"  {i}. {script:25s} → {desc}")
    print()

    total_start = time.time()

    for i, (script, desc, required) in enumerate(STEPS, 1):
        print(f"\n{'=' * 60}")
        print(f"  步骤 {i}/{len(STEPS)}")
        print(f"{'=' * 60}")
        ok = run_step(script, desc, required)
        if not ok and required:
            print(f"\n{'!' * 60}")
            print(f"  执行中断：步骤 {i}（{script}）失败")
            print(f"  请修复后重新运行：python scripts/reseed_all.py")
            print(f"  （已执行的步骤会幂等处理，不会产生重复数据）")
            print(f"{'!' * 60}")
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print()
    print("=" * 60)
    print(f"  全部完成！共 {len(STEPS)} 个步骤，总耗时 {total_elapsed:.1f}s")
    print()
    print("  数据已按《精密五金工厂设备与产品》文档重新生成：")
    print("    - 设备类型: CNC车床/CNC加工中心/冲床/激光切割机/数控折弯机/线切割/磨床/空压机")
    print("    - 设备: 200 台（按文档占比）")
    print("    - 故障码: 104 条（8类×13条，6位纯数字编码）")
    print("    - 工单: 200 单（含双录入模式：日志型/现象型）")
    print("    - 知识: ~106 条（50条工单知识 + 56条独立知识）")
    print("    - 备件: ~50 种（从故障模板沉淀）")
    print("    - Milvus 向量: 已同步")
    print()
    print("  访问: http://localhost:4173")
    print("  API:  http://localhost:18080/docs")
    print("=" * 60)


if __name__ == "__main__":
    main()
