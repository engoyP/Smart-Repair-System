"""Embedding 编码服务（OpenAI 兼容接口）

复用 app.core.embeddings 的 Qwen3-Embedding-0.6B 编码逻辑，
暴露 OpenAI 兼容的 /v1/embeddings 接口，供 RAGFlow 等外部系统作为
向量模型源调用（本地部署，不依赖外部 API）。

启动方式：
    python -m app.core.embedding_server
    # 或指定端口
    python -m app.core.embedding_server --port 8010
"""
import argparse
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.embeddings import encode_text, encode_texts


class EmbeddingRequest(BaseModel):
    """OpenAI /v1/embeddings 请求体"""
    model: str = Field(default=settings.EMBEDDING_MODEL_NAME)
    input: List[str] = Field(..., min_length=1)
    encoding_format: Optional[str] = Field(None, description="仅支持 float，base64 暂不支持")


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[dict]
    model: str
    usage: dict


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🫙 Embedding 服务启动中，预加载模型...")
    try:
        from app.core.embeddings import _load_model
        _load_model()
        from app.core.embeddings import get_vector_dimension
        logger.info(f"🧠 Embedding 模型加载完成，维度={get_vector_dimension()}")
    except Exception as e:
        logger.error(f"⚠️ Embedding 模型加载失败: {e}")
        raise
    yield
    logger.info("👋 Embedding 服务关闭中...")


app = FastAPI(
    title="Embedding Server (OpenAI Compatible)",
    description="本地 Qwen3-Embedding-0.6B 编码服务，供 RAGFlow 等系统调用",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def embeddings(req: EmbeddingRequest):
    """文本编码为向量（OpenAI 兼容格式）"""
    if req.encoding_format == "base64":
        raise HTTPException(status_code=400, detail="base64 编码暂不支持，请使用 float")
    try:
        vectors = encode_texts(req.input, max_length=settings.EMBEDDING_MAX_LENGTH)
    except Exception as e:
        logger.error(f"编码失败: {e}")
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


@app.get("/v1/models")
def models():
    """列出可用模型"""
    return {
        "object": "list",
        "data": [{"id": settings.EMBEDDING_MODEL_NAME, "object": "model"}],
    }


@app.get("/health")
def health():
    """健康检查：确认模型已加载"""
    from app.core.embeddings import get_vector_dimension
    return {"status": "ok", "model": settings.EMBEDDING_MODEL_NAME, "dim": get_vector_dimension()}


def main():
    parser = argparse.ArgumentParser(description="本地 Embedding 服务")
    parser.add_argument("--host", default=settings.EMBEDDING_SERVER_HOST)
    parser.add_argument("--port", type=int, default=settings.EMBEDDING_SERVER_PORT)
    args = parser.parse_args()

    import uvicorn
    # 模型加载耗时较长，放宽超时避免日志报错
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
