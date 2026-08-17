"""统一推理服务（OpenAI 兼容）— bge-m3 召回编码 + Qwen3-Reranker-0.6B 精排打分

承担两类职责（纯 CPU 部署，单进程双模型，约 5GB 内存）：
1. 召回编码：bge-m3 dense 向量（1024 维），/v1/embeddings（OpenAI 兼容，供 RAGFlow 等外部系统）
2. 精排打分：Qwen3-Reranker-0.6B cross-encoder 打分，/v1/rerank

主链路（backend 进程）通过 HTTP 调用本服务，模型推理与业务解耦：
- 模型可独立升级/扩缩容（生产 GPU 形态用 vLLM/SGLang 托管同类模型，接口不变）
- 主链路启动不加载模型，避免内存占用与启动阻塞

启动方式：
    python -m app.core.embedding_server
    # 或指定端口
    python -m app.core.embedding_server --port 8010
"""
import argparse
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import List, Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings

# 本地模型路径（优先加载，无则从 HF 镜像下载）
_EMBEDDING_LOCAL_CANDIDATES = [
    r"D:\models\BAAI\BAAI__bge-m3",
    r"D:\models\BAAI\bge-m3",
    r"D:\models\bge-m3",
]
_RERANKER_LOCAL_CANDIDATES = [
    r"D:\models\Qwen\Qwen3-Reranker-0___6B",
    r"D:\models\Qwen\Qwen3-Reranker-0.6B",
    r"D:\models\Qwen3-Reranker-0.6B",
]

# 模块级单例（进程内只加载一次）
_embed_model = None          # BGEM3FlagModel
_reranker_model = None       # FlagReranker 或 transformers 手动加载的模型
_reranker_tokenizer = None
_reranker_kind = None        # "flag" | "hf"
_VECTOR_DIM = None
_started_at = None

# 每个模型一把锁，后台线程加载 + 端点懒加载共用（double-check，加载期间请求阻塞等待）
_embed_lock = threading.Lock()
_rerank_lock = threading.Lock()
_embed_load_error = None
_rerank_load_error = None


def _resolve_model_path(candidates: List[str], hf_name: str) -> str:
    """本地路径优先，无则返回 HF 模型名（走 hf-mirror 下载）"""
    for p in candidates:
        if os.path.isdir(p):
            return p
    return hf_name


def _load_embedding_model():
    """加载 bge-m3（FlagEmbedding BGEM3FlagModel，dense 1024 维已 L2 归一化）
    线程安全：double-check + 锁，后台线程与端点懒加载并发调用只加载一次"""
    global _embed_model, _VECTOR_DIM, _embed_load_error
    if _embed_model is not None:
        return
    with _embed_lock:
        if _embed_model is not None:
            return
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        model_path = _resolve_model_path(_EMBEDDING_LOCAL_CANDIDATES, settings.EMBEDDING_MODEL_NAME)

        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError:
            _embed_load_error = "FlagEmbedding 未安装，请先 pip install -r requirements.txt"
            raise RuntimeError(_embed_load_error)

        logger.info(f"加载 bge-m3 模型: {model_path} (device=cpu)")
        t0 = time.time()
        _embed_model = BGEM3FlagModel(
            model_path,
            use_fp16=False,           # CPU 用 fp32，避免 fp16 精度损失
            # 必须用 devices（复数）固定 CPU：新版 FlagEmbedding 不认 device= 参数，
            # devices=None 自动探测在 CUDA_VISIBLE_DEVICES="" 时得到空列表 → 多进程池 0 进程 → 除零 500
            devices="cpu",
        )
        _VECTOR_DIM = _embed_model.model.config.hidden_size
        logger.info(f"bge-m3 加载完成，维度={_VECTOR_DIM}，耗时 {time.time()-t0:.1f}s")


def _load_reranker():
    """加载 Qwen3-Reranker-0.6B：FlagReranker 优先，版本不支持则 transformers 手动加载
    线程安全：double-check + 锁"""
    global _reranker_model, _reranker_tokenizer, _reranker_kind, _rerank_load_error
    if _reranker_model is not None:
        return
    with _rerank_lock:
        if _reranker_model is not None:
            return
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        model_path = _resolve_model_path(_RERANKER_LOCAL_CANDIDATES, settings.RERANKER_MODEL_NAME)

        t0 = time.time()
        # 方案 1：FlagReranker（官方支持 qwen3-reranker 系列，normalize 开箱即用）
        try:
            from FlagEmbedding import FlagReranker
            _reranker_model = FlagReranker(model_path, use_fp16=False, devices="cpu")
            # 冒烟打分：transformers 5.x 移除 prepare_for_model 后，旧版 FlagReranker 构造能过
            # 但 compute_score 会炸（Qwen2Tokenizer has no attribute prepare_for_model），
            # 加载时自检一次，失败走下方 transformers 手动加载
            _reranker_model.compute_score([["加载自检", "加载自检"]], normalize=True)
            _reranker_kind = "flag"
            logger.info(f"Qwen3-Reranker 加载完成 (FlagReranker)，耗时 {time.time()-t0:.1f}s")
            return
        except Exception as e:
            logger.warning(f"FlagReranker 加载失败，回退 transformers 手动加载: {e}")
            _reranker_model = None

        # 方案 2：transformers 手动加载（decoder-only，取末尾 token 的 Yes/No logits，sigmoid）
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            _reranker_tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
            _reranker_model = AutoModelForCausalLM.from_pretrained(
                model_path, trust_remote_code=True, dtype=torch.float32,
            )
            _reranker_model.eval()
            _reranker_kind = "hf"
            logger.info(f"Qwen3-Reranker 加载完成 (transformers)，耗时 {time.time()-t0:.1f}s")
        except Exception as e:
            _rerank_load_error = f"Qwen3-Reranker 加载失败: {e}"
            raise RuntimeError(_rerank_load_error)


def _background_load():
    """后台线程加载双模型：进程可立即接受连接，/health 如实报告 loading/ready/error"""
    logger.info("后台线程开始加载模型（bge-m3 + Qwen3-Reranker，纯 CPU 约 2-5 分钟）...")
    try:
        _load_embedding_model()
    except Exception as e:
        _embed_load_error = str(e)
        logger.error(f"⚠️ bge-m3 加载失败: {e}")
    try:
        _load_reranker()
    except Exception as e:
        _rerank_load_error = str(e)
        logger.error(f"⚠️ Qwen3-Reranker 加载失败: {e}")
    if _embed_model is not None and _reranker_model is not None:
        logger.info(f"✅ 双模型加载完成，推理服务就绪（耗时 {time.time()-_started_at:.1f}s）")
    else:
        logger.error("❌ 模型加载未完全成功，请检查上面的错误日志")


def _rerank_scores(query: str, documents: List[str]) -> List[float]:
    """对 (query, doc) 对批量打分，返回 0~1 归一化分数（与 documents 同序）"""
    if _reranker_kind == "flag":
        pairs = [[query, d] for d in documents]
        # normalize=True 输出 sigmoid 归一化分数
        scores = _reranker_model.compute_score(pairs, normalize=True)
        if isinstance(scores, (int, float, np.floating)):
            scores = [float(scores)]
        return [float(s) for s in scores]

    # transformers 手动加载：Qwen3-Reranker 输出 2 类 logits（No/Yes），取末尾 token 的 Yes 分数
    import torch
    inputs = _reranker_tokenizer(
        [f"{query}{_reranker_tokenizer.eos_token}{d}" for d in documents],
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=settings.EMBEDDING_MAX_LENGTH * 4,
    )
    with torch.no_grad():
        logits = _reranker_model(**inputs).logits            # [B, L, 2]
        last_logits = logits[:, -1, :]                        # [B, 2]
        scores = torch.sigmoid(last_logits[:, 1] - last_logits[:, 0])  # Yes vs No
    return scores.tolist()


class EmbeddingRequest(BaseModel):
    """OpenAI /v1/embeddings 请求体"""
    model: str = Field(default=settings.EMBEDDING_MODEL_NAME)
    input: List[str] = Field(..., min_length=1)
    max_length: Optional[int] = Field(None, description="编码最大 token 数（默认取服务配置）")
    encoding_format: Optional[str] = Field(None, description="仅支持 float，base64 暂不支持")


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[dict]
    model: str
    usage: dict


class RerankRequest(BaseModel):
    """/v1/rerank 请求体（对齐 Cohere/SGLang rerank 接口语义）"""
    model: str = Field(default=settings.RERANKER_MODEL_NAME)
    query: str = Field(..., description="查询文本")
    documents: List[str] = Field(..., min_length=1, description="待打分文档列表")
    top_n: Optional[int] = Field(None, description="返回前 N 个（不传返回全部）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _started_at
    _started_at = time.time()
    # 非阻塞：后台线程加载双模型，进程立即接受连接，/health 如实报告 loading/ready
    logger.info("🚀 推理服务启动中，后台线程预加载模型（纯 CPU 约 2-5 分钟），/health 可立即查询...")
    threading.Thread(target=_background_load, name="model-loader", daemon=True).start()
    yield
    logger.info("👋 推理服务关闭中...")


app = FastAPI(
    title="Inference Server (OpenAI Compatible)",
    description="本地 bge-m3 召回编码 + Qwen3-Reranker-0.6B 精排打分服务",
    version="2.0.0",
    lifespan=lifespan,
)


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def embeddings(req: EmbeddingRequest):
    """文本编码为向量（OpenAI 兼容格式，批量）"""
    if req.encoding_format == "base64":
        raise HTTPException(status_code=400, detail="base64 编码暂不支持，请使用 float")
    try:
        _load_embedding_model()
        # bge-m3 dense 输出已 L2 归一化，batch 编码
        # FlagEmbedding>=1.3 改用 return_colbert_vecs / dense_vecs 键名，勿回退旧参数
        out = _embed_model.encode(
            req.input,
            max_length=req.max_length or settings.EMBEDDING_MAX_LENGTH,
            return_dense=True, return_sparse=False, return_colbert_vecs=False,
            batch_size=16,
        )
        vectors = out["dense_vecs"].astype(np.float32).tolist()
    except Exception as e:
        logger.exception(f"编码失败: {e}")
        raise HTTPException(status_code=500, detail=f"Embedding 编码失败: {e}")

    data = [
        {"object": "embedding", "index": i, "embedding": vec}
        for i, vec in enumerate(vectors)
    ]
    return EmbeddingResponse(
        data=data,
        model=req.model,
        usage={"prompt_tokens": 0, "total_tokens": 0},
    )


@app.post("/v1/rerank")
def rerank(req: RerankRequest):
    """对 (query, document) 批量打分，按分数降序返回 top_n"""
    try:
        _load_reranker()
        scores = _rerank_scores(req.query, req.documents)
    except Exception as e:
        logger.error(f"重排打分失败: {e}")
        raise HTTPException(status_code=500, detail=f"Rerank 打分失败: {e}")

    ranked = sorted(
        ({"index": i, "score": round(s, 4)} for i, s in enumerate(scores)),
        key=lambda x: x["score"], reverse=True,
    )
    if req.top_n is not None:
        ranked = ranked[: req.top_n]
    return {"object": "list", "model": req.model, "results": ranked}


@app.get("/v1/models")
def models():
    """列出可用模型"""
    return {
        "object": "list",
        "data": [
            {"id": settings.EMBEDDING_MODEL_NAME, "object": "model"},
            {"id": settings.RERANKER_MODEL_NAME, "object": "model"},
        ],
    }


@app.get("/health")
def health():
    """健康检查：如实报告双模型加载状态（后台线程加载，本接口不触发阻塞加载）"""
    load_secs = round(time.time() - _started_at, 1) if _started_at else None
    embedding_ready = _embed_model is not None
    rerank_ready = _reranker_model is not None
    if embedding_ready and rerank_ready:
        status = "ok"
    elif _embed_load_error is not None or _rerank_load_error is not None:
        status = "error"
    else:
        status = "loading"
    return {
        "status": status,
        "embedding_model": settings.EMBEDDING_MODEL_NAME,
        "rerank_model": settings.RERANKER_MODEL_NAME,
        "dim": _VECTOR_DIM,
        "embedding_ready": embedding_ready,
        "rerank_ready": rerank_ready,
        "load_error": _embed_load_error or _rerank_load_error or "",
        "load_secs": load_secs,
    }


def main():
    parser = argparse.ArgumentParser(description="本地推理服务（bge-m3 编码 + Qwen3-Reranker 重排）")
    parser.add_argument("--host", default=settings.EMBEDDING_SERVER_HOST)
    parser.add_argument("--port", type=int, default=settings.EMBEDDING_SERVER_PORT)
    args = parser.parse_args()

    import uvicorn
    # 模型加载耗时较长，放宽超时避免日志报错
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
