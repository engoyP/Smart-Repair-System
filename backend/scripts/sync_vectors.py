"""同步脚本：将 PostgreSQL 中已有的知识条目重新导入 Milvus 向量库"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.core.vector_store import vector_store
from app.core.embeddings import encode_text
from loguru import logger

logger.add(sys.stdout, colorize=True, level="INFO")

db = SessionLocal()
try:
    # 查询所有已发布的知识条目
    items = db.query(KnowledgeItem).filter(
        KnowledgeItem.status == KnowledgeStatus.PUBLISHED
    ).all()
    logger.info(f"PostgreSQL 中共有 {len(items)} 条已发布知识条目")

    success = 0
    failed = 0
    skipped = 0

    for item in items:
        try:
            text = f"{item.title or ''}\n{item.content[:500] if item.content else ''}"
            if not text.strip():
                skipped += 1
                continue

            vec = encode_text(text)
            vector_store.insert(
                vector=vec,
                knowledge_id=item.id,
                title=item.title or "",
                content=item.content or "",
                device_type=item.device_type or "",
                fault_code=item.fault_code or "",
                fault_tags=item.fault_tags or [],
            )
            success += 1
            if success % 50 == 0:
                logger.info(f"  已处理 {success} 条...")
        except Exception as e:
            failed += 1
            logger.error(f"  失败 id={item.id}: {e}")

    if success > 0:
        vector_store.flush()

    logger.info(f"同步完成: 成功 {success}, 跳过 {skipped}, 失败 {failed}")
    logger.info(f"Milvus 当前向量总数: {vector_store.count()}")
finally:
    db.close()
