"""将所有知识条目重新同步向量到 Milvus（使用 Qwen3-Embedding-0.6B）"""
import time
from loguru import logger
from app.core.database import SessionLocal
from app.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.core.vector_store import vector_store
from app.core.embeddings import encode_text

BATCH_SIZE = 10

# 关闭 SQLAlchemy 引擎日志，避免刷屏
import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def run():
    print("正在重新同步知识向量到 Milvus...")
    print("  使用模型: Qwen3-Embedding-0.6B (1024维)")
    print()

    # 先清空已有 Milvus 集合中的旧向量
    print("[1/4] 清空 Milvus 旧向量...")
    try:
        count_before = vector_store.count()
        print(f"  当前 Milvus 中 {count_before} 条向量")

        # 删除集合并重建（维度一致，都是1024）
        collection_name = vector_store.collection_name
        from pymilvus import utility
        if utility.has_collection(collection_name):
            vector_store._lazy_init()
            # 删除所有数据
            vector_store._collection.delete(expr="id != ''")
            vector_store._collection.flush()
            print(f"  已清空集合 {collection_name}")
    except Exception as e:
        print(f"  ⚠️ 清空失败: {e}")

    # 重置所有知识条目的 milvus_id
    db = SessionLocal()
    try:
        print("\n[2/4] 重置知识条目 milvus_id...")
        db.query(KnowledgeItem).update({"milvus_id": None})
        db.commit()
        print("  已重置所有知识条目的 milvus_id")

        # 获取所有已发布的知识条目
        print("\n[3/4] 读取已发布知识条目...")
        items = db.query(KnowledgeItem).filter(
            KnowledgeItem.status == KnowledgeStatus.PUBLISHED
        ).order_by(KnowledgeItem.id).all()
        print(f"  共 {len(items)} 条知识待同步")

        # 批量同步
        print("\n[4/4] 开始向量编码与同步...")
        success = 0
        fail = 0
        start = time.time()

        for i, item in enumerate(items, 1):
            try:
                # 拼接编码文本
                text = f"{item.title} {item.content[:2000]}"
                vec = encode_text(text)

                # 插入 Milvus
                point_id = vector_store.insert(
                    vector=vec,
                    knowledge_id=item.id,
                    title=item.title,
                    content=item.content[:500],
                    device_type=item.device_type,
                    fault_code=item.fault_code,
                    fault_tags=item.fault_tags or [],
                )

                # 更新 PostgreSQL 中的 milvus_id
                item.milvus_id = point_id

                success += 1
                if i % BATCH_SIZE == 0 or i == len(items):
                    db.commit()
                    elapsed = time.time() - start
                    print(f"  进度: {i}/{len(items)} | 成功: {success} | 耗时: {elapsed:.0f}s")

            except Exception as e:
                fail += 1
                print(f"  ❌ #{item.id} {item.title[:30]}... 失败: {e}")

        db.commit()

        # 批量插入完成后统一 flush 一次
        if success > 0:
            vector_store.flush()
            print(f"  向量数据已刷写落盘")

        elapsed = time.time() - start
        print(f"\n{'='*50}")
        print(f"✅ 向量同步完成！")
        print(f"   总条目: {len(items)}")
        print(f"   成功: {success}")
        print(f"   失败: {fail}")
        print(f"   耗时: {elapsed:.0f}s")
        print(f"{'='*50}")

    except Exception as e:
        db.rollback()
        print(f"\n❌ 同步失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
