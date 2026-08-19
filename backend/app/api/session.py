"""会话管理 API - 摘要压缩"""
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from loguru import logger

from app.agents.session_summarizer import session_summarizer

router = APIRouter()


class MessageItem(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class SummarizeRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    messages: List[MessageItem] = Field(..., min_length=2, description="待压缩的消息列表")


class SummarizeResponse(BaseModel):
    session_id: str
    summary: str
    compressed_count: int
    time_ms: float


@router.post("/summarize", response_model=SummarizeResponse, summary="会话摘要压缩")
def summarize_session(request: SummarizeRequest):
    """将会话历史消息压缩为结构化摘要，用于替代原始消息降低存储"""
    start = time.time()
    try:
        messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]
        summary = session_summarizer.summarize(messages_dict)
        elapsed = (time.time() - start) * 1000
        return SummarizeResponse(
            session_id=request.session_id,
            summary=summary,
            compressed_count=len(request.messages),
            time_ms=round(elapsed, 1),
        )
    except Exception as e:
        logger.error(f"会话摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"摘要生成失败: {str(e)}")
