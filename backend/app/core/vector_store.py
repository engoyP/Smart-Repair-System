from pymilvus import (
    connections, Collection, FieldSchema, CollectionSchema,
    DataType, utility
)
from typing import List, Dict, Optional
from app.core.config import settings
import uuid
from loguru import logger


class VectorStore:
    """Milvus 向量存储服务封装（懒加载模式）"""

    def __init__(self):
        self.host = settings.MILVUS_HOST
        self.port = settings.MILVUS_PORT
        self.collection_name = settings.MILVUS_COLLECTION
        self.vector_size = settings.MILVUS_VECTOR_SIZE
        self._collection = None
        self._connected = False

    def _lazy_init(self):
        """首次使用时初始化连接和集合"""
        if not self._connected:
            self._connect()
            self._ensure_collection()
            self._connected = True

    def _connect(self):
        """连接 Milvus"""
        try:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port
            )
            logger.info(f"已连接 Milvus: {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"连接 Milvus 失败: {e}")
            raise

    def _ensure_collection(self):
        """确保集合存在、索引已创建、已加载到内存"""
        try:
            if utility.has_collection(self.collection_name):
                logger.info(f"Milvus 集合已存在: {self.collection_name}")
                self._collection = Collection(self.collection_name)
                # 确保索引存在，不存在则创建
                if not self._collection.has_index():
                    self._create_index()
                self._collection.load()
            else:
                self._create_collection()
        except Exception as e:
            logger.error(f"Milvus 集合初始化失败: {e}")
            raise

    def _create_collection(self):
        """创建集合"""
        fields = [
            FieldSchema(
                name="id",
                dtype=DataType.VARCHAR,
                is_primary=True,
                max_length=100,
                description="向量 ID"
            ),
            FieldSchema(
                name="vector",
                dtype=DataType.FLOAT_VECTOR,
                dim=self.vector_size,
                description="向量数据"
            ),
            FieldSchema(
                name="knowledge_id",
                dtype=DataType.INT64,
                description="关联 PostgreSQL 知识条目 ID"
            ),
            FieldSchema(
                name="title",
                dtype=DataType.VARCHAR,
                max_length=500,
                description="知识标题"
            ),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=65535,
                description="知识内容"
            ),
            FieldSchema(
                name="device_type",
                dtype=DataType.VARCHAR,
                max_length=100,
                description="设备类型"
            ),
            FieldSchema(
                name="fault_code",
                dtype=DataType.VARCHAR,
                max_length=500,
                description="故障码，多个用逗号分隔"
            ),
            FieldSchema(
                name="fault_tags",
                dtype=DataType.JSON,
                description="故障标签"
            ),
        ]

        schema = CollectionSchema(
            fields=fields,
            description="企业维修知识条目向量集合"
        )

        self._collection = Collection(
            name=self.collection_name,
            schema=schema
        )

        self._create_index()

        logger.info(f"创建 Milvus 集合: {self.collection_name}, 向量维度: {self.vector_size}")

    def _create_index(self):
        """创建向量索引并加载集合"""
        index_params = [
            {
                "field_name": "vector",
                "index_params": {
                    "index_type": "IVF_FLAT",
                    "metric_type": "COSINE",
                    "params": {"nlist": 1024}
                }
            }
        ]
        self._collection.create_index(field_name="vector", index_params=index_params[0]["index_params"])
        self._collection.load()
        logger.info(f"Milvus 索引创建成功: {self.collection_name}")

    def insert(
        self,
        vector: List[float],
        knowledge_id: int,
        title: str,
        content: str,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        fault_tags: Optional[List] = None,
        point_id: Optional[str] = None
    ) -> str:
        """插入向量

        Args:
            vector: 向量数据
            knowledge_id: PostgreSQL 知识条目 ID
            title: 知识标题
            content: 知识内容
            device_type: 设备类型
            fault_code: 故障码
            fault_tags: 故障标签
            point_id: 向量 ID（自动生成如未指定）

        Returns:
            向量 ID
        """
        self._lazy_init()
        if point_id is None:
            point_id = str(uuid.uuid4())

        data = [
            [point_id],  # id
            [vector],   # vector
            [knowledge_id],  # knowledge_id
            [title],  # title
            [content[:65000] if content else ""],  # content (截断到 65535)
            [device_type or ""],  # device_type
            [fault_code or ""],  # fault_code
            [fault_tags or []],  # fault_tags
        ]

        try:
            self._collection.insert(data)
            logger.debug(f"向量插入成功: {point_id}")
            return point_id
        except Exception as e:
            logger.error(f"向量插入失败: {e}")
            raise

    def flush(self):
        """手动刷写向量数据到磁盘（批量插入完成后调用一次即可）"""
        self._lazy_init()
        try:
            self._collection.flush()
            logger.debug("向量数据已刷写到磁盘")
        except Exception as e:
            logger.error(f"向量刷写失败: {e}")
            raise

    def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        score_threshold: float = 0.3
    ) -> List[Dict]:
        """向量相似度搜索

        Args:
            query_vector: 查询向量
            limit: 返回结果数量
            device_type: 设备类型过滤
            fault_code: 故障码过滤
            score_threshold: 相似度阈值

        Returns:
            [{id, score, knowledge_id, title, ...}, ...]
        """
        self._lazy_init()
        expr_parts = []
        if device_type:
            expr_parts.append(f'device_type == "{device_type}"')
        if fault_code:
            expr_parts.append(f'fault_code like "%{fault_code}%"')

        expr = " and ".join(expr_parts) if expr_parts else None

        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 16}
        }

        results = self._collection.search(
            data=[query_vector],
            anns_field="vector",
            param=search_params,
            limit=limit,
            expr=expr,
            output_fields=["knowledge_id", "title", "content", "device_type", "fault_code", "fault_tags"]
        )

        output = []
        for hits in results:
            for hit in hits:
                if hit.score >= score_threshold:
                    output.append({
                        "id": hit.id,
                        "score": hit.score,
                        "knowledge_id": hit.entity.get("knowledge_id"),
                        "title": hit.entity.get("title", ""),
                        "content": hit.entity.get("content", ""),
                        "device_type": hit.entity.get("device_type", ""),
                        "fault_code": hit.entity.get("fault_code", ""),
                        "fault_tags": hit.entity.get("fault_tags", [])
                    })

        return output

    def update(
        self,
        point_id: str,
        vector: Optional[List[float]] = None,
        title: Optional[str] = None,
        content: Optional[str] = None,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        fault_tags: Optional[List] = None
    ) -> bool:
        """更新向量或元数据"""
        self._lazy_init()
        try:
            # Milvus 2.x 使用 upsert 更新
            fields_data = {
                "id": [point_id],
            }

            if vector is not None:
                fields_data["vector"] = [vector]
            if title is not None:
                fields_data["title"] = [title]
            if content is not None:
                fields_data["content"] = [content[:65000] if content else ""]
            if device_type is not None:
                fields_data["device_type"] = [device_type]
            if fault_code is not None:
                fields_data["fault_code"] = [fault_code]
            if fault_tags is not None:
                fields_data["fault_tags"] = [fault_tags]

            self._collection.upsert(fields_data)
            logger.debug(f"向量更新成功: {point_id}")
            return True
        except Exception as e:
            logger.error(f"向量更新失败: {e}")
            return False

    def delete(self, point_id: str) -> bool:
        """删除向量"""
        self._lazy_init()
        try:
            self._collection.delete(expr=f'id == "{point_id}"')
            logger.debug(f"向量删除成功: {point_id}")
            return True
        except Exception as e:
            logger.error(f"向量删除失败: {e}")
            return False

    def get_by_id(self, point_id: str) -> Optional[Dict]:
        """根据 ID 获取向量"""
        self._lazy_init()
        try:
            results = self._collection.query(
                expr=f'id == "{point_id}"',
                output_fields=["vector", "knowledge_id", "title", "content", "device_type", "fault_code", "fault_tags"]
            )
            if results:
                row = results[0]
                return {
                    "id": row["id"],
                    "vector": row.get("vector"),
                    "knowledge_id": row.get("knowledge_id"),
                    "title": row.get("title", ""),
                    "content": row.get("content", ""),
                    "device_type": row.get("device_type", ""),
                    "fault_code": row.get("fault_code", ""),
                    "fault_tags": row.get("fault_tags", [])
                }
            return None
        except Exception as e:
            logger.error(f"向量查询失败: {e}")
            return None

    def count(self) -> int:
        """获取向量总数"""
        self._lazy_init()
        try:
            # 用 query 方式获取数量，兼容性更好
            results = self._collection.query(
                expr="id != ''",
                output_fields=["count(*)"]
            )
            if results:
                return results[0].get("count(*)", 0)
            return 0
        except Exception as e:
            logger.error(f"向量计数失败: {e}")
            return 0

    def drop_collection(self):
        """删除集合（危险操作）"""
        self._lazy_init()
        try:
            self._collection.drop()
            logger.warning(f"已删除 Milvus 集合: {self.collection_name}")
        except Exception as e:
            logger.error(f"删除集合失败: {e}")


vector_store = VectorStore()