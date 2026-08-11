from pymilvus import (
    connections, Collection, FieldSchema, CollectionSchema,
    DataType, utility
)
from typing import List, Dict, Optional
from app.core.config import settings
import uuid
from loguru import logger


class VectorStore:
    """Milvus 向量存储服务封装（懒加载模式，支持多集合泛化）

    基类默认管理知识库集合（knowledge）；子类可传不同的集合名/字段 schema，
    复用同一套连接、建集合、索引、刷写逻辑。
    """

    # 知识库集合（knowledge）默认字段
    _KNOWLEDGE_FIELDS = [
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
            dim=settings.MILVUS_VECTOR_SIZE,
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

    # 知识库集合搜索/查询默认输出字段
    _KNOWLEDGE_OUTPUT_FIELDS = ["knowledge_id", "title", "content", "device_type", "fault_code", "fault_tags"]

    def __init__(self, collection_name: Optional[str] = None, fields: Optional[List] = None,
                 description: str = ""):
        self.host = settings.MILVUS_HOST
        self.port = settings.MILVUS_PORT
        self.collection_name = collection_name or settings.MILVUS_COLLECTION
        self.vector_size = settings.MILVUS_VECTOR_SIZE
        self._fields = fields if fields is not None else self._KNOWLEDGE_FIELDS
        self._description = description or f"Milvus 集合: {self.collection_name}"
        self._output_fields = self._KNOWLEDGE_OUTPUT_FIELDS
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
        """创建集合（schema 由子类传入的 fields 决定）"""
        schema = CollectionSchema(
            fields=self._fields,
            description=self._description
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
        """插入向量（知识库集合专用字段）

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
        """向量相似度搜索（知识库集合）

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
            output_fields=self._output_fields
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
        """更新向量或元数据（知识库集合专用字段）"""
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
        """根据 ID 获取向量（知识库集合字段）"""
        self._lazy_init()
        try:
            results = self._collection.query(
                expr=f'id == "{point_id}"',
                output_fields=self._output_fields
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


class LogCodeVectorStore(VectorStore):
    """设备手册错误码向量存储（log_code 集合）

    只存设备说明书/维修手册中的"错误码 → 故障诊断"条目，
    与知识库集合（knowledge）完全隔离；检索时双库并行召回再融合。
    """

    _LOG_CODE_FIELDS = [
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
            dim=settings.MILVUS_VECTOR_SIZE,
            description="向量数据"
        ),
        FieldSchema(
            name="manual_code_id",
            dtype=DataType.INT64,
            description="关联 PostgreSQL 手册条目 ID"
        ),
        FieldSchema(
            name="error_code",
            dtype=DataType.VARCHAR,
            max_length=100,
            description="错误码/报警码"
        ),
        FieldSchema(
            name="manual_name",
            dtype=DataType.VARCHAR,
            max_length=300,
            description="设备说明书/手册名称"
        ),
        FieldSchema(
            name="device_type",
            dtype=DataType.VARCHAR,
            max_length=100,
            description="设备类型"
        ),
        FieldSchema(
            name="title",
            dtype=DataType.VARCHAR,
            max_length=500,
            description="错误码标题"
        ),
        FieldSchema(
            name="description",
            dtype=DataType.VARCHAR,
            max_length=65535,
            description="错误含义/触发条件"
        ),
        FieldSchema(
            name="chapter",
            dtype=DataType.VARCHAR,
            max_length=200,
            description="所属章节"
        ),
        FieldSchema(
            name="page",
            dtype=DataType.VARCHAR,
            max_length=50,
            description="页码"
        ),
    ]

    _LOG_CODE_OUTPUT_FIELDS = [
        "manual_code_id", "error_code", "manual_name", "device_type",
        "title", "description", "chapter", "page",
    ]

    def __init__(self):
        super().__init__(
            collection_name=settings.MILVUS_LOG_CODE_COLLECTION,
            fields=self._LOG_CODE_FIELDS,
            description="设备手册错误码-故障诊断向量集合",
        )
        self._output_fields = self._LOG_CODE_OUTPUT_FIELDS

    def insert(
        self,
        vector: List[float],
        manual_code_id: int,
        error_code: str,
        manual_name: str,
        device_type: Optional[str],
        title: str,
        description: str,
        chapter: str = "",
        page: str = "",
        point_id: Optional[str] = None
    ) -> str:
        """插入手册错误码向量（log_code 集合专用字段）

        Args:
            vector: 向量数据（对 description 编码）
            manual_code_id: PostgreSQL 手册条目 ID
            error_code: 错误码/报警码
            manual_name: 说明书/手册名称
            device_type: 设备类型
            title: 错误码标题
            description: 错误含义/触发条件
            chapter: 所属章节（出处）
            page: 页码（出处）
            point_id: 向量 ID（自动生成如未指定）

        Returns:
            向量 ID
        """
        self._lazy_init()
        if point_id is None:
            point_id = str(uuid.uuid4())

        data = [
            [point_id],        # id
            [vector],          # vector
            [manual_code_id],  # manual_code_id
            [error_code],      # error_code
            [manual_name],     # manual_name
            [device_type or ""],   # device_type
            [title],           # title
            [description[:65000] if description else ""],  # description (截断到 65535)
            [chapter or ""],   # chapter
            [page or ""],      # page
        ]

        try:
            self._collection.insert(data)
            logger.debug(f"手册错误码向量插入成功: {point_id}")
            return point_id
        except Exception as e:
            logger.error(f"手册错误码向量插入失败: {e}")
            raise

    def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        device_type: Optional[str] = None,
        error_code: Optional[str] = None,
        score_threshold: float = 0.0
    ) -> List[Dict]:
        """向量语义搜索手册错误码条目（可叠加 device_type / error_code 过滤）

        Args:
            query_vector: 查询向量（对提问文本编码）
            limit: 返回结果数量
            device_type: 设备类型过滤
            error_code: 错误码精确过滤
            score_threshold: 相似度阈值

        Returns:
            [{id, score, manual_code_id, error_code, title, description, chapter, page, ...}, ...]
        """
        self._lazy_init()
        expr_parts = []
        if device_type:
            expr_parts.append(f'device_type == "{device_type}"')
        if error_code:
            expr_parts.append(f'error_code == "{error_code}"')

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
            output_fields=self._output_fields
        )

        output = []
        for hits in results:
            for hit in hits:
                if hit.score >= score_threshold:
                    output.append({
                        "id": hit.id,
                        "score": hit.score,
                        "manual_code_id": hit.entity.get("manual_code_id"),
                        "error_code": hit.entity.get("error_code", ""),
                        "manual_name": hit.entity.get("manual_name", ""),
                        "device_type": hit.entity.get("device_type", ""),
                        "title": hit.entity.get("title", ""),
                        "description": hit.entity.get("description", ""),
                        "chapter": hit.entity.get("chapter", ""),
                        "page": hit.entity.get("page", ""),
                    })

        return output


# 全局单例
vector_store = VectorStore()              # 知识库集合（knowledge）
log_code_store = LogCodeVectorStore()     # 设备手册错误码集合（log_code）
