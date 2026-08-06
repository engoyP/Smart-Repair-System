"""知识检索 API - 混合检索（向量 + BM25 + RRF）+ ReAct Agent + 分析型问答"""
import time
import json
from fastapi import APIRouter, Query, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.orm import Session
from loguru import logger

from app.core.database import get_db, SessionLocal
from app.core.vector_store import vector_store
from app.core.embeddings import encode_text
from app.agents.tools import RetrievalTools, rrf_merge, weighted_rerank
from app.agents.retrieval_agent import RetrievalAssistantAgent
from app.agents.answer_agent import answer_agent
from app.agents.guided_repair_agent import guided_repair_agent

router = APIRouter()


# ==================== 请求/响应模型 ====================

class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索关键词或自然语言描述")
    device_type: Optional[str] = Field(None, description="设备类型筛选")
    fault_code: Optional[str] = Field(None, description="故障码筛选")
    top_k: Optional[int] = Field(10, ge=1, le=50)
    mode: Optional[str] = Field("agent", description="检索模式: agent | hybrid | vector | bm25")


class SearchResultItem(BaseModel):
    knowledge_id: int
    title: str
    content: str
    device_type: Optional[str] = ""
    fault_code: Optional[str] = ""
    fault_tags: Optional[List[str]] = []
    score: float
    source: str  # vector / bm25 / conditional / graph


class SearchResponse(BaseModel):
    query: str
    mode: str
    total: int
    results: List[SearchResultItem]
    strategies_used: List[str] = []
    rewrite_count: int = 0
    rewritten_queries: List[str] = []
    total_time_ms: float = 0.0
    scratchpad: Optional[List[dict]] = None


class AnswerRequest(BaseModel):
    question: str = Field(..., description="用户的维修问题")
    device_type: Optional[str] = Field(None, description="设备类型筛选")
    fault_code: Optional[str] = Field(None, description="故障码筛选")
    top_k: Optional[int] = Field(10, ge=3, le=20)


class ReferenceCaseItem(BaseModel):
    knowledge_id: int
    title: str
    content: str
    device_type: str = ""
    fault_code: str = ""
    score: float = 0.0
    summary: str = ""


class AnswerResponse(BaseModel):
    question: str
    answer: str
    references: List[ReferenceCaseItem] = []
    confidence: float = 0.0
    sources_count: int = 0
    retrieval_time_ms: float = 0.0
    answer_time_ms: float = 0.0
    total_time_ms: float = 0.0


# ==================== 工具工厂 ====================

def _make_tools() -> RetrievalTools:
    return RetrievalTools(
        db_session_factory=SessionLocal,
        vector_store=vector_store,
        embedding_fn=encode_text,
    )


# ==================== API 端点 ====================

@router.get("/quick", summary="快速语义检索")
def quick_search(
    q: str = Query(..., description="搜索内容"),
    device_type: Optional[str] = Query(None),
    fault_code: Optional[str] = Query(None),
    top_k: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """快速语义检索 - 仅向量检索，适合自动补全等场景"""
    try:
        tools = _make_tools()
        result = tools.vector_search(
            query=q,
            top_k=top_k,
            device_type=device_type,
            fault_code=fault_code,
            score_threshold=0.3,
        )
        results = []
        for item in result.data:
            results.append({
                "knowledge_id": item.get("knowledge_id") or item.get("id"),
                "title": item.get("title", ""),
                "content": item.get("content", "")[:300],
                "device_type": item.get("device_type", ""),
                "fault_code": item.get("fault_code", ""),
                "fault_tags": item.get("fault_tags", []),
                "score": round(item.get("score", 0), 4),
            })
        return {"query": q, "total": len(results), "results": results}
    except Exception as e:
        logger.error(f"快速检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")


@router.post("/hybrid", response_model=SearchResponse, summary="混合检索（无Agent）")
def hybrid_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
):
    """向量 + BM25 混合检索 + RRF 融合排序（确定性流程，无 ReAct）"""
    tools = _make_tools()
    import time; start = time.time()

    # 并行执行向量和 BM25 检索
    vector_result = tools.vector_search(query=request.query, top_k=request.top_k,
                                         device_type=request.device_type, fault_code=request.fault_code,
                                         score_threshold=0.15)
    bm25_result = tools.bm25_search(query=request.query, top_k=request.top_k,
                                     device_type=request.device_type, fault_code=request.fault_code)

    # RRF 融合
    result_sets = []
    if vector_result.success:
        result_sets.append(vector_result.data)
    if bm25_result.success:
        result_sets.append(bm25_result.data)

    merged = rrf_merge(result_sets, top_n=request.top_k) if result_sets else []

    # 格式化输出
    results = []
    for item in merged:
        results.append(SearchResultItem(
            knowledge_id=item.get("knowledge_id") or item.get("id", 0),
            title=item.get("title", ""),
            content=(item.get("content", "") or "")[:500],
            device_type=item.get("device_type", ""),
            fault_code=item.get("fault_code", ""),
            fault_tags=item.get("fault_tags", []) if isinstance(item.get("fault_tags"), list) else [],
            score=round(item.get("score", item.get("rrf_score", 0)), 4),
            source="hybrid",
        ))

    elapsed = (time.time() - start) * 1000
    return SearchResponse(
        query=request.query,
        mode="hybrid",
        total=len(results),
        results=results,
        strategies_used=["vector_search", "bm25_search"],
        total_time_ms=round(elapsed, 1),
    )


@router.post("/agent", response_model=SearchResponse, summary="Agent 智能检索（ReAct 循环）")
def agent_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
):
    """
    使用 RetrievalAssistantAgent 的完整 ReAct 检索流程。

    流程：思考 → 选择策略 → 执行检索 → 观察结果 → 判断质量 →
          不足则改写查询 → 重试 → 直到满足要求或达到最大迭代次数
    """
    try:
        tools = _make_tools()
        agent = RetrievalAssistantAgent(tools=tools)

        result = agent.search(
            query=request.query,
            device_type=request.device_type,
            fault_code=request.fault_code,
            max_results=request.top_k,
        )

        # 格式化结果
        results = []
        for item in result.results:
            results.append(SearchResultItem(
                knowledge_id=item.get("knowledge_id") or item.get("id", 0),
                title=item.get("title", ""),
                content=(item.get("content", "") or "")[:500],
                device_type=item.get("device_type", ""),
                fault_code=item.get("fault_code", ""),
                fault_tags=item.get("fault_tags", []) if isinstance(item.get("fault_tags"), list) else [],
                score=round(item.get("score", item.get("rrf_score", 0)), 4),
                source=result.strategies_used[0] if result.strategies_used else "agent",
            ))

        # 构建 scratchpad 输出
        scratchpad_out = []
        for step in result.scratchpad:
            scratchpad_out.append({
                "step": step.step,
                "thought": step.thought,
                "action": step.action,
                "tool_input": step.tool_input,
                "observation": step.observation,
            })

        return SearchResponse(
            query=result.query,
            mode="agent",
            total=len(results),
            results=results,
            strategies_used=result.strategies_used,
            rewrite_count=result.rewrite_count,
            rewritten_queries=result.rewritten_queries,
            total_time_ms=result.total_time_ms,
            scratchpad=scratchpad_out,
        )
    except Exception as e:
        logger.error(f"Agent 检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"Agent 检索失败: {str(e)}")


# ==================== 分析型问答 ====================

@router.post("/answer/stream", summary="分析型问答（流式 SSE）")
async def analyze_answer_stream(
    request: AnswerRequest,
    db: Session = Depends(get_db),
):
    """
    流式分析型问答：先检索历史案例，再基于案例流式生成分析回答（SSE）。

    事件类型：
    - {"type": "thinking"} — AI 正在检索分析中
    - {"type": "answer", "content": "..."} — 片段内容
    - {"type": "done", "confidence": 0.8, "sources_count": 3} — 完成
    """
    import json as json_module

    async def stream():
        # 立即响应，让前端显示"正在思考..."
        yield f"data: {json_module.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        # Step 0: 库存查询前置
        if answer_agent.is_inventory_query(request.question):
            from app.models.spare_part import SparePart
            result = answer_agent.handle_inventory_query(request.question, db)
            yield f"data: {json_module.dumps({'type': 'answer', 'content': result.answer}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        # Step 1: 混合检索
        try:
            tools = _make_tools()
            vector_result = tools.vector_search(
                query=request.question, top_k=request.top_k,
                device_type=request.device_type, fault_code=request.fault_code,
                score_threshold=0.0,
            )
            bm25_result = tools.bm25_search(
                query=request.question, top_k=request.top_k,
                device_type=request.device_type, fault_code=request.fault_code,
            )
            result_sets = []
            if vector_result.success:
                result_sets.append(vector_result.data)
            if bm25_result.success:
                result_sets.append(bm25_result.data)
            merged = rrf_merge(result_sets, top_n=request.top_k) if result_sets else []
        except Exception as e:
            logger.error(f"检索阶段失败: {e}")
            merged = []

        # 过滤 + 加权重排
        filtered_merged = [m for m in merged if not m.get("rrf_only", False) and m.get("score", 0) >= 0.15]
        # 提取技术关键词传给 weighted_rerank，避免干扰词影响打分
        cleaned_q = tools.query_extractor.extract(request.question, use_llm_fallback=False)
        filtered_merged = weighted_rerank(filtered_merged, request.question,
                                          fault_weight=0.4, device_penalty=0.15,
                                          cleaned_query=cleaned_q)
        filtered_merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        # 重排后再次过滤：确保低于阈值的案例不送入 LLM 也不展示
        filtered_merged = [m for m in filtered_merged if m.get("score", 0) >= 0.15][:8]

        # Step 2: 发送参考案例
        references = []
        for ref in filtered_merged:
            if len(references) >= 8: break
            references.append({
                "knowledge_id": ref.get("knowledge_id") or ref.get("id", 0),
                "title": ref.get("title", ""),
                "content": (ref.get("content", "") or "")[:200],
                "device_type": ref.get("device_type", ""),
                "fault_code": ref.get("fault_code", ""),
                "score": ref.get("score", 0),
                "summary": ref.get("summary", ""),
            })
        yield f"event: references\ndata: {json_module.dumps(references, ensure_ascii=False)}\n\n"

        # Step 3: 流式生成 LLM 回答
        try:
            for sse_msg in answer_agent.stream_answer(request.question, filtered_merged):
                yield sse_msg
        except Exception as e:
            logger.error(f"流式生成失败: {e}")
            yield f"data: {json_module.dumps({'type': 'answer', 'content': f'生成失败: {e}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': len(references)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/answer", response_model=AnswerResponse, summary="分析型问答（检索+生成）")
def analyze_answer(
    request: AnswerRequest,
    db: Session = Depends(get_db),
):
    """
    分析型问答：先检索历史案例，再基于案例生成分析回答。

    流程：
    1. 使用混合检索（向量+BM25）获取相关历史案例
    2. 将案例传入 AnswerAgent 生成分析回答
    3. 返回生成的回答 + 参考案例列表
    """
    total_start = time.time()
    retrieval_start = time.time()

    # Step 0: 库存查询前置判断
    if answer_agent.is_inventory_query(request.question):
        try:
            result = answer_agent.handle_inventory_query(request.question, db)
            return AnswerResponse(
                question=request.question,
                answer=result.answer,
                references=[],
                confidence=0,
                sources_count=0,
                retrieval_time_ms=round((time.time() - total_start) * 1000, 1),
                answer_time_ms=0,
                total_time_ms=round((time.time() - total_start) * 1000, 1),
            )
        except Exception as e:
            logger.error(f"库存查询异常: {e}")

    # Step 1: 混合检索
    try:
        tools = _make_tools()

        vector_result = tools.vector_search(
            query=request.question,
            top_k=request.top_k,
            device_type=request.device_type,
            fault_code=request.fault_code,
            score_threshold=0.0,
        )
        bm25_result = tools.bm25_search(
            query=request.question,
            top_k=request.top_k,
            device_type=request.device_type,
            fault_code=request.fault_code,
        )

        result_sets = []
        if vector_result.success:
            result_sets.append(vector_result.data)
        if bm25_result.success:
            result_sets.append(bm25_result.data)

        merged = rrf_merge(result_sets, top_n=request.top_k) if result_sets else []
        retrieval_time_ms = (time.time() - retrieval_start) * 1000

    except Exception as e:
        logger.error(f"检索阶段失败: {e}")
        merged = []
        retrieval_time_ms = (time.time() - retrieval_start) * 1000

    # Step 1.5: 过滤 BM25 独中条目（无语义匹配的去掉）
    # 阈值 0.15：低于 15% 相关度的案例视为不相关
    filtered_merged = [m for m in merged if not m.get("rrf_only", False) and m.get("score", 0) >= 0.15]

    # 加权重排序：故障原因匹配度 > 设备类型匹配度
    # 提取技术关键词传给 weighted_rerank，避免干扰词影响打分
    cleaned_q = tools.query_extractor.extract(request.question, use_llm_fallback=False)
    filtered_merged = weighted_rerank(filtered_merged, request.question,
                                      fault_weight=0.4, device_penalty=0.15,
                                      cleaned_query=cleaned_q)

    # 按加权后分数降序排列
    filtered_merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    # 重排后再次过滤：确保低于阈值的案例不送入 LLM 也不展示
    filtered_merged = [m for m in filtered_merged if m.get("score", 0) >= 0.15][:8]

    # Step 2: AnswerAgent 生成分析回答
    answer_start = time.time()
    result = answer_agent.answer(request.question, filtered_merged)
    answer_time_ms = (time.time() - answer_start) * 1000

    # Step 3: 格式化输出（按评分降序，同分按录入时间倒序，最多 8 条）
    references = []
    sorted_refs = sorted(result.references, key=lambda r: (-r.score, -r.knowledge_id))
    # 展示用分数下限（与检索过滤一致）：0.30
    for ref in sorted_refs:
        if ref.score < 0.15:
            continue
        if len(references) >= 8:
            break
        references.append(ReferenceCaseItem(
            knowledge_id=ref.knowledge_id,
            title=ref.title,
            content=ref.content[:200],
            device_type=ref.device_type,
            fault_code=ref.fault_code,
            score=ref.score,
            summary=ref.summary,
        ))

    total_time_ms = (time.time() - total_start) * 1000

    return AnswerResponse(
        question=request.question,
        answer=result.answer,
        references=references,
        confidence=result.confidence,
        sources_count=result.sources_count,
        retrieval_time_ms=round(retrieval_time_ms, 1),
        answer_time_ms=round(answer_time_ms, 1),
        total_time_ms=round(total_time_ms, 1),
    )


# ==================== 追踪维修引导 ====================

class GuidedRepairStartRequest(BaseModel):
    description: str = Field(..., min_length=2, max_length=500)
    device_type: Optional[str] = None


class GuidedRepairStepRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    selected_option: str = Field(..., description="选择的选项ID，如 A/B/C")
    action_taken: str = Field(..., min_length=1, max_length=1000, description="执行了什么操作")
    device_status: str = Field(..., min_length=1, max_length=500, description="操作后设备状态")


class RepairOptionOut(BaseModel):
    id: str
    cause: str
    diagnostic_action: str


class GuidedRepairStepOut(BaseModel):
    session_id: str
    step: int
    message: str
    options: List[RepairOptionOut] = []
    status: str = "awaiting_action"
    summary: str = ""


@router.post("/guided-repair/start", response_model=GuidedRepairStepOut, summary="开始追踪维修")
def start_guided_repair(request: GuidedRepairStartRequest):
    """根据故障描述启动追踪维修诊断"""
    result = guided_repair_agent.start_diagnosis(
        description=request.description,
        device_type=request.device_type or "",
    )
    return GuidedRepairStepOut(
        session_id=result.session_id,
        step=result.step,
        message=result.message,
        options=[RepairOptionOut(id=o.id, cause=o.cause, diagnostic_action=o.diagnostic_action)
                 for o in result.options],
        status=result.status,
        summary=result.summary,
    )


@router.post("/guided-repair/{session_id}/step", response_model=GuidedRepairStepOut, summary="追踪维修下一步")
def guided_repair_next_step(session_id: str, request: GuidedRepairStepRequest):
    """维修员反馈操作结果，AI 给出下一步诊断"""
    result = guided_repair_agent.next_step(
        session_id=session_id,
        selected_option=request.selected_option,
        action_taken=request.action_taken,
        device_status=request.device_status,
    )
    return GuidedRepairStepOut(
        session_id=result.session_id,
        step=result.step,
        message=result.message,
        options=[RepairOptionOut(id=o.id, cause=o.cause, diagnostic_action=o.diagnostic_action)
                 for o in result.options],
        status=result.status,
        summary=result.summary,
    )


# ==================== 对话式追踪维修（流式） ====================

class GuidedRepairChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="维修员消息")
    session_id: Optional[str] = Field(None, description="追踪会话ID，首次为空则自动创建")
    device_type: Optional[str] = Field(None, description="设备类型")


@router.post("/guided-repair/chat", summary="对话式追踪维修（流式 SSE）")
async def guided_repair_chat_stream(request: GuidedRepairChatRequest):
    """对话式追踪维修：维修员发自然语言消息，AI 流式返回引导回复。

    事件类型：
    - {"type": "thinking"} — AI 正在检索分析中
    - {"type": "answer", "content": "..."} — 片段内容
    - {"type": "done", "session_id": "xxx"} — 完成
    """
    import json as json_module
    import uuid
    import asyncio

    sid = request.session_id or str(uuid.uuid4())[:8]

    async def stream():
        yield f"data: {json_module.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        try:
            # 使用新的 achat 异步方法，原生 async for，无死锁风险
            async for chunk in guided_repair_agent.achat(
                session_id=sid,
                message=request.message,
                device_type=request.device_type or "",
            ):
                if hasattr(chunk, 'content') and chunk.content:
                    yield f"data: {json_module.dumps({'type': 'answer', 'content': chunk.content}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"[GuidedChat] 流式生成失败: {e}")
            yield f"data: {json_module.dumps({'type': 'answer', 'content': f'生成失败: {str(e)[:100]}'}, ensure_ascii=False)}\n\n"

        yield f"data: {json_module.dumps({'type': 'done', 'session_id': sid}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
