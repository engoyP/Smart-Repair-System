"""Embedding 客户端 - HTTP 调用统一推理服务（bge-m3 编码）

模型推理已抽到独立服务（app.core.embedding_server，端口 8010），
本模块是主链路（FastAPI 进程 + 数据脚本）的 HTTP 客户端：
- 保持同名 API（encode_text / encode_texts / get_vector_dimension），调用点零改动
- 服务不可用时：encode_* 抛 RuntimeError（调用方决定降级），is_server_available() 供快速探测

依赖推理服务已启动（start_all.ps1 / start_embedding_server.ps1 负责启动并等待就绪）。
"""
from typing import List, Optional

import httpx
from loguru import logger

from app.core.config import settings

_SERVER_URL = settings.EMBEDDING_SERVER_URL.rstrip("/")
_TIMEOUT = 30.0          # 单次编码请求超时（CPU 批量编码可能较慢）
_RETRIES = 2             # 失败重试次数
_HTTP = httpx.Client(timeout=_TIMEOUT)


def is_server_available() -> bool:
    """快速探测推理服务是否可用（短超时，用于降级判断）"""
    try:
        r = _HTTP.get(f"{_SERVER_URL}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _call_embeddings(texts: List[str], max_length: int) -> List[List[float]]:
    """调用 /v1/embeddings，带重试；失败抛 RuntimeError"""
    last_err: Optional[Exception] = None
    for attempt in range(_RETRIES + 1):
        try:
            r = _HTTP.post(
                f"{_SERVER_URL}/v1/embeddings",
                json={"model": settings.EMBEDDING_MODEL_NAME, "input": texts,
                      "max_length": max_length},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()["data"]
            data.sort(key=lambda x: x["index"])
            return [d["embedding"] for d in data]
        except Exception as e:
            last_err = e
            if attempt < _RETRIES:
                logger.warning(f"Embedding 服务调用失败（第 {attempt+1} 次），重试: {e}")
    raise RuntimeError(
        f"Embedding 服务不可用（{_SERVER_URL}）: {last_err}。请先启动推理服务："
        "start_all.ps1 或 python -m app.core.embedding_server"
    )


def get_vector_dimension() -> int:
    """获取向量维度（从推理服务健康检查读取，失败回退配置值）"""
    try:
        r = _HTTP.get(f"{_SERVER_URL}/health", timeout=2.0)
        r.raise_for_status()
        dim = r.json().get("dim")
        if dim:
            return int(dim)
    except Exception:
        pass
    return settings.MILVUS_VECTOR_SIZE


def encode_text(text: str, max_length: int = 512) -> List[float]:
    """将文本编码为 1024 维向量（bge-m3 dense，已 L2 归一化）"""
    return _call_embeddings([text], max_length)[0]


def encode_texts(texts: List[str], max_length: int = 512) -> List[List[float]]:
    """批量编码（一次 HTTP 请求，比逐个调用高效）"""
    return _call_embeddings(texts, max_length)
