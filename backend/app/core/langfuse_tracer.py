"""LLM 追踪模块（多后端：RAGFlow / LangFuse / 本地日志）

统一的追踪抽象层，支持：
- RAGFlow 后端：将 trace/generation/score 写入 RAGFlow 指定知识库
- LangFuse 后端：使用 LangFuse v4 SDK
- Local 后端：降级到内存日志

当 RAGFlow/LangFuse 不可达时自动降级到 local，不影响业务。
"""
import time
import json
import uuid
import threading
from typing import Optional, Dict, Any, List, Callable
from contextlib import contextmanager
from loguru import logger
from functools import wraps

import requests

from app.core.config import settings


class RAGFlowClient:
    """RAGFlow REST API 封装，用于追踪数据持久化"""

    def __init__(self, host: str, api_key: str, traces_dataset: str):
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.traces_dataset = traces_dataset
        self._dataset_id: Optional[str] = None
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def _get(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.host}{path}"
        return self._session.get(url, **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.host}{path}"
        return self._session.post(url, **kwargs)

    def _delete(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.host}{path}"
        return self._session.delete(url, **kwargs)

    def ping(self) -> bool:
        """测试是否可达"""
        try:
            r = self._get("/api/v1/datasets", timeout=3)
            return r.status_code in (200, 401, 403)
        except Exception:
            return False

    def ensure_traces_dataset(self) -> Optional[str]:
        """确保追踪数据集存在，返回 dataset_id"""
        if self._dataset_id:
            return self._dataset_id
        with self._lock:
            if self._dataset_id:
                return self._dataset_id
            try:
                r = self._get("/api/v1/datasets", timeout=5)
                if r.status_code == 200:
                    datasets = r.json().get("data", [])
                    for ds in datasets:
                        if ds.get("name") == self.traces_dataset:
                            self._dataset_id = ds.get("id")
                            logger.info(f"[RAGFlow] 使用已有追踪数据集: {self.traces_dataset}")
                            return self._dataset_id
            except Exception as e:
                logger.warning(f"[RAGFlow] 列举数据集失败: {e}")

            try:
                r = self._post(
                    "/api/v1/datasets",
                    json={
                        "name": self.traces_dataset,
                        "description": "LLM 调用追踪数据（自动生成）",
                        "chunk_method": "naive",
                        "embedding_model": "BAAI/bge-m3@OpenAI-API-Compatible",
                        "permission": "me",
                    },
                    timeout=10,
                )
                if r.status_code == 200:
                    self._dataset_id = r.json().get("data", {}).get("id")
                    logger.info(f"[RAGFlow] 创建追踪数据集: {self.traces_dataset} ({self._dataset_id})")
                    return self._dataset_id
                logger.warning(f"[RAGFlow] 创建数据集失败: {r.status_code} {r.text[:200]}")
            except Exception as e:
                logger.warning(f"[RAGFlow] 创建数据集异常: {e}")
        return None

    def upload_trace(self, trace_record: Dict[str, Any]) -> Optional[str]:
        """将一条完整 trace 作为文档写入 RAGFlow（适配 v0.26 流程）

        1) POST /api/v1/files（multipart 上传 trace JSON，创建文件记录）
        2) POST /api/v1/files/link-to-datasets（文件关联到数据集并触发解析）
        """
        dataset_id = self.ensure_traces_dataset()
        if not dataset_id:
            return None
        try:
            trace_id = trace_record.get("trace_id", str(uuid.uuid4()))
            content = json.dumps(trace_record, ensure_ascii=False, indent=2)
            filename = f"trace_{trace_id}.json"

            r = self._session.post(
                f"{self.host}/api/v1/files",
                files={"file": (filename, content.encode("utf-8"), "application/json")},
                headers={"Content-Type": None},  # 让 requests 自动生成 multipart boundary
                timeout=30,
            )
            if r.status_code != 200:
                logger.debug(f"[RAGFlow] 上传 trace 文件失败: {r.status_code} {r.text[:200]}")
                return None
            data = r.json().get("data", [])
            file_id = data[0].get("id") if isinstance(data, list) and data else None
            if not file_id:
                logger.debug(f"[RAGFlow] trace 文件响应异常: {r.text[:200]}")
                return None

            r2 = self._session.post(
                f"{self.host}/api/v1/files/link-to-datasets",
                json={"file_ids": [file_id], "kb_ids": [dataset_id]},
                timeout=30,
            )
            if r2.status_code == 200 and r2.json().get("code") == 0:
                logger.info(f"[RAGFlow] trace 关联数据集成功: {filename} -> file_id={file_id[:12]}")
                return file_id
            logger.debug(f"[RAGFlow] 关联 trace 到数据集失败: {r2.status_code} {r2.text[:200]}")
            return None
        except Exception as e:
            logger.debug(f"[RAGFlow] 上传 trace 异常: {e}")
            return None


class Tracer:
    """统一追踪器，支持多后端（延迟连接 + 自动重试）"""

    def __init__(self):
        self._backend: str = settings.TRACING_BACKEND
        self._ragflow: Optional[RAGFlowClient] = None
        self._ragflow_verified: bool = False
        self._langfuse_client = None
        self._local_logs: List[Dict] = []
        self._ragflow_buffer: List[Dict[str, Any]] = []

        if self._backend == "ragflow":
            if settings.RAGFLOW_ENABLED and settings.RAGFLOW_API_KEY:
                self._ragflow = RAGFlowClient(
                    settings.RAGFLOW_HOST,
                    settings.RAGFLOW_API_KEY,
                    settings.RAGFLOW_TRACES_DATASET,
                )
                if self._ragflow.ping():
                    self._ragflow_verified = True
                    logger.info(f"[Tracer] RAGFlow 追踪已启用 ({settings.RAGFLOW_HOST})")
                else:
                    logger.warning(f"[Tracer] RAGFlow 启动时不可达，将在首次使用时重试")
            else:
                logger.info("[Tracer] RAGFlow 未启用，使用本地日志模式")
        elif self._backend == "langfuse":
            try:
                from langfuse import Langfuse as _LangfuseClient, observe as _OBSERVE
                if settings.LANGFUSE_PUBLIC_KEY:
                    self._langfuse_client = _LangfuseClient(
                        public_key=settings.LANGFUSE_PUBLIC_KEY,
                        secret_key=settings.LANGFUSE_SECRET_KEY or "unused",
                        host=settings.LANGFUSE_HOST,
                    )
                    self._langfuse_observe = _OBSERVE
                    logger.info("[Tracer] LangFuse 追踪已启用")
                else:
                    logger.info("[Tracer] LangFuse 未配置，使用本地日志")
            except ImportError:
                logger.warning("[Tracer] langfuse SDK 未安装")
            except Exception as e:
                logger.warning(f"[Tracer] LangFuse 初始化失败: {e}")

    def _ensure_ragflow(self) -> bool:
        """懒加载 + 重试连接 RAGFlow"""
        if self._ragflow_verified:
            return True
        if self._ragflow is None:
            if self._backend != "ragflow" or not settings.RAGFLOW_ENABLED or not settings.RAGFLOW_API_KEY:
                return False
            self._ragflow = RAGFlowClient(
                settings.RAGFLOW_HOST,
                settings.RAGFLOW_API_KEY,
                settings.RAGFLOW_TRACES_DATASET,
            )
        try:
            if self._ragflow.ping():
                self._ragflow_verified = True
                logger.info(f"[Tracer] RAGFlow 连接成功 ({settings.RAGFLOW_HOST})")
                return True
        except Exception:
            pass
        return False

    @property
    def enabled(self) -> bool:
        return (self._ragflow is not None and self._ragflow_verified) or self._langfuse_client is not None

    def trace(self, name: str, metadata: Optional[Dict] = None):
        return _TraceContext(self, name, metadata or {})

    def observe(self, name: str, as_type: str = "span", **kwargs):
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kw):
                start = time.time()
                try:
                    result = func(*args, **kw)
                    self._local_logs.append({
                        "type": as_type,
                        "name": name,
                        "duration_ms": round((time.time() - start) * 1000, 1),
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "status": "success",
                    })
                    return result
                except Exception as e:
                    self._local_logs.append({
                        "type": as_type,
                        "name": name,
                        "duration_ms": round((time.time() - start) * 1000, 1),
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "status": "error",
                        "error": str(e),
                    })
                    raise
            return wrapper
        return decorator

    def score(self, name: str, value: float, trace_id: Optional[str] = None,
              comment: str = ""):
        if self._ragflow and trace_id:
            for rec in self._ragflow_buffer:
                if rec.get("trace_id") == trace_id:
                    rec.setdefault("scores", []).append({
                        "name": name,
                        "value": value,
                        "comment": comment,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    })
                    return
        self._local_logs.append({
            "type": "score",
            "name": name,
            "value": value,
            "comment": comment,
            "trace_id": trace_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    def _enqueue_trace(self, record: Dict[str, Any]):
        """将一条完整 trace 加入 RAGFlow 缓冲（懒加载连接）"""
        if not self._ensure_ragflow():
            logger.warning(f"[Tracer] _ensure_ragflow 失败，跳过 trace: {record.get('name')}")
            return
        try:
            self._ragflow_buffer.append(record)
            logger.info(f"[Tracer] trace 已入缓冲: {record.get('name')} (id={record.get('trace_id', 'N/A')[:12]})")
            if len(self._ragflow_buffer) >= 1:
                self._flush_ragflow_buffer()
        except Exception as e:
            logger.error(f"[Tracer] RAGFlow 缓冲异常: {e}")

    def _flush_ragflow_buffer(self):
        if not self._ensure_ragflow() or not self._ragflow_buffer:
            return
        records = self._ragflow_buffer
        self._ragflow_buffer = []
        logger.info(f"[Tracer] 刷新 RAGFlow 缓冲: {len(records)} 条 trace")
        for rec in records:
            try:
                doc_id = self._ragflow.upload_trace(rec)
                if doc_id:
                    logger.info(f"[Tracer] trace 上传成功: {rec.get('name')} -> doc_id={doc_id[:12]}")
                else:
                    logger.warning(f"[Tracer] trace 上传返回 None: {rec.get('name')}")
            except Exception as e:
                logger.error(f"[Tracer] RAGFlow flush 失败: {e}")

    def get_logs(self, last_n: int = 50) -> List[Dict]:
        return self._local_logs[-last_n:]

    def get_ragflow_traces(self) -> List[Dict[str, Any]]:
        return list(self._ragflow_buffer)

    def flush(self):
        self._flush_ragflow_buffer()


class _TraceContext:
    def __init__(self, tracer: Tracer, name: str, metadata: Dict):
        self._tracer = tracer
        self._name = name
        self._metadata = metadata
        self._trace_id = str(uuid.uuid4())
        self._start = time.time()
        self._events: List[Dict[str, Any]] = []
        self._scores: List[Dict[str, Any]] = []

    def __enter__(self):
        self._events.append({
            "type": "trace_enter",
            "name": self._name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        self._tracer._local_logs.append({
            "type": "trace_enter",
            "name": self._name,
            "trace_id": self._trace_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = round((time.time() - self._start) * 1000, 1)
        self._events.append({
            "type": "trace_exit",
            "name": self._name,
            "duration_ms": duration_ms,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        self._tracer._local_logs.append({
            "type": "trace_exit",
            "name": self._name,
            "duration_ms": duration_ms,
            "trace_id": self._trace_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

        record = {
            "trace_id": self._trace_id,
            "name": self._name,
            "metadata": self._metadata,
            "duration_ms": duration_ms,
            "events": self._events,
            "scores": self._scores,
            "status": "error" if exc_type else "ok",
        }
        if exc_type:
            record["error"] = str(exc_val)
        self._tracer._enqueue_trace(record)
        return False

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def generation(self, name: str, model: str, prompt: str, response: str,
                   metadata: Optional[Dict] = None):
        return _GenerationContext(self, name, model, prompt, response, metadata or {})

    def score(self, name: str, value: float, comment: str = ""):
        self._scores.append({
            "name": name,
            "value": value,
            "comment": comment,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })


class _GenerationContext:
    def __init__(self, trace_ctx: _TraceContext, name: str, model: str,
                 prompt: str, response: str, metadata: Dict):
        self._trace_ctx = trace_ctx
        self._name = name
        self._model = model
        self._prompt = prompt
        self._response = response
        self._metadata = metadata
        self._start = time.time()

    def __enter__(self):
        self._trace_ctx._events.append({
            "type": "generation_enter",
            "name": self._name,
            "model": self._model,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        self._trace_ctx._tracer._local_logs.append({
            "type": "generation_enter",
            "name": self._name,
            "model": self._model,
            "trace_id": self._trace_ctx._trace_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = round((time.time() - self._start) * 1000, 1)
        self._trace_ctx._events.append({
            "type": "generation_exit",
            "name": self._name,
            "model": self._model,
            "duration_ms": duration_ms,
            "prompt_length": len(self._prompt) if self._prompt else 0,
            "response_length": len(self._response) if self._response else 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        self._trace_ctx._tracer._local_logs.append({
            "type": "generation_exit",
            "name": self._name,
            "duration_ms": duration_ms,
            "model": self._model,
            "trace_id": self._trace_ctx._trace_id,
            "prompt_length": len(self._prompt) if self._prompt else 0,
            "response_length": len(self._response) if self._response else 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return False


tracer = Tracer()
