"""同步脚本：将 PostgreSQL 中已有的知识条目重新导入 Milvus 向量库

支持目标集合无损迁移（--target-collection）：新向量写入新集合，验证通过后再
切换配置（MILVUS_COLLECTION），旧集合保留可回滚，避免"清空一半"的中间态。

幂等：对同一 knowledge_id 先删旧向量再插入，可安全重跑。

使用方式:
    cd backend
    python scripts/sync_vectors.py                        # 默认集合（settings.MILVUS_COLLECTION）
    python scripts/sync_vectors.py --target-collection knowledge_bgem3   # 迁移到新集合

前提条件:
    - 推理服务已启动（bge-m3 编码走 HTTP）：start_all.ps1 或 python -m app.core.embedding_server
    - PostgreSQL 已启动，Milvus 已启动
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.core.vector_store import VectorStore, vector_store
from app.core.embeddings import encode_text, is_server_available


def check_inference_server():
    """推理服务连通性检查（服务化后，向量脚本必须先启动推理服务）"""
    if not is_server_available():
        logger.error(f"推理服务不可用: {settings.EMBEDDING_SERVER_URL}")
        logger.error("请先启动推理服务：start_all.ps1 或 python -m app.core.embedding_server")
        sys.exit(1)


def main(target_collection: str):
    check_inference_server()
    store = VectorStore(collection_name=target_collection) if target_collection else vector_store
    store_name = target_collection or settings.MILVUS_COLLECTION

    db = SessionLocal()
    try:
        # 查询所有已发布的知识条目
        items = db.query(KnowledgeItem).filter(
            KnowledgeItem.status == KnowledgeStatus.PUBLISHED
        ).all()
        logger.info(f"PostgreSQL 中共有 {len(items)} 条已发布知识条目，目标集合: {store_name}")

        success = 0
        failed = 0
        skipped = 0

        for item in items:
            try:
                text = f"{item.title or ''}\n{(item.content or '')[:settings.MAX_VECTOR_CONTENT_LEN]}"
                if not text.strip():
                    skipped += 1
                    continue

                vec = encode_text(text)
                # 幂等：先删同 knowledge_id 的旧向量，再插入（可安全重跑）
                store.delete_by_knowledge_id(item.id)
                store.insert(
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
            store.flush()

        logger.info(f"同步完成: 成功 {success}, 跳过 {skipped}, 失败 {failed}")
        logger.info(f"Milvus 集合 {store_name} 当前向量总数: {store.count()}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PG 知识条目 → Milvus 向量同步")
    parser.add_argument("--target-collection", default="",
                        help="目标集合名（默认 settings.MILVUS_COLLECTION；无损迁移时指定新集合）")
    args = parser.parse_args()
    main(args.target_collection)
