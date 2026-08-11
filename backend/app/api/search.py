"""知识检索 API - 混合检索（向量 + BM25 + RRF）+ ReAct Agent + 分析型问答"""
import time
import json
import asyncio
from fastapi import APIRouter, Query, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.orm import Session
from loguru import logger

from app.core.database import get_db
from app.agents.tools import RetrievalTools, rrf_merge
from app.agents.retrieval_flow import (
    make_tools as _make_tools,
    extract_device_and_fault as _extract_device_and_fault,
    filter_rerank_cases as _filter_rerank_cases,
)
from app.agents.retrieval_agent import RetrievalAssistantAgent
from app.agents.answer_agent import answer_agent
from app.agents.fault_decomposer import fault_decomposer
from app.agents.guided_repair_agent import guided_repair_agent

router = APIRouter()


# ==================== 请求/响应模型 ====================
# Pydantic 数据模型（数据契约）：只定义接口的数据结构，不执行任何逻辑。
# FastAPI 用它自动完成：①校验请求 ②JSON↔Python对象转换 ③生成 Swagger 文档。

class SearchRequest(BaseModel):
    """搜索请求：客户端发来"搜什么"时的数据格式"""
    query: str = Field(..., description="搜索关键词或自然语言描述")      # 必填（... = 无默认值，必须传）
    device_type: Optional[str] = Field(None, description="设备类型筛选")  # 可选，不传=不过滤（如"注塑机"）
    fault_code: Optional[str] = Field(None, description="故障码筛选")    # 可选，不传=不过滤（如"6401"）
    top_k: Optional[int] = Field(10, ge=1, le=50)                        # 返回条数：默认10，限制1~50
    mode: Optional[str] = Field("agent", description="检索模式: agent | hybrid | vector | bm25")  # 检索策略，默认agent


class SearchResultItem(BaseModel):
    """单条搜索结果：对应前端展示的一张知识卡片"""
    knowledge_id: int              # 知识库主键（全局唯一身份，RRF融合的去重键）
    title: str                     # 案例标题
    content: str                   # 案例正文内容
    device_type: Optional[str] = ""    # 设备类型（默认空串，避免前端显示 undefined）
    fault_code: Optional[str] = ""     # 故障码（默认空串）
    fault_tags: Optional[List[str]] = []  # 故障标签数组（如["温控","加热器"]）
    score: float                   # 相关度分数 0~1，越接近1越相关（各接口口径不同，见接口实现）
    source: str  # vector / bm25 / conditional / graph   # 这条结果来自哪条检索路


class SearchResponse(BaseModel):
    """搜索接口的整体响应：把多条结果 + 检索元信息打包返回"""
    query: str                                   # 回显用户搜索的原话
    mode: str                                    # 这次实际走的检索模式（agent / hybrid 等）
    total: int                                   # 返回结果总数
    results: List[SearchResultItem]              # 结果列表（每个元素是上面那个模型）
    strategies_used: List[str] = []              # 实际用了哪几条检索策略（如 vector_search / bm25_search）
    rewrite_count: int = 0                       # 查询改写了几次（仅 /agent 有值）
    rewritten_queries: List[str] = []            # 改写出来的查询词列表
    total_time_ms: float = 0.0                   # 总耗时（毫秒）
    scratchpad: Optional[List[dict]] = None      # Agent 的推理过程（思考/行动/观察），仅 /agent 返回，调试用


class AnswerRequest(BaseModel):
    """问答请求：客户端发来"问一个问题"时的数据格式"""
    question: str = Field(..., description="用户的维修问题")     # 必填，问题文本
    device_type: Optional[str] = Field(None, description="设备类型筛选")  # 可选，缩小检索范围
    fault_code: Optional[str] = Field(None, description="故障码筛选")    # 可选，缩小检索范围
    top_k: Optional[int] = Field(10, ge=3, le=20)   # 检索案例数：默认10，限制3~20（至少3条供LLM参考）


class ManualLookupRequest(BaseModel):
    """工单错误码录入预填请求：输入设备错误码或故障描述，返回手册标准处理 + 工单案例"""
    query: str = Field(..., min_length=1, max_length=200, description="错误码（如 SV0436 / 6401）或故障描述")
    top_k: Optional[int] = Field(5, ge=1, le=10, description="每类返回条数上限")


# ==================== 工具工厂 ====================
# _make_tools 已移至公共编排层 app/agents/retrieval_flow.make_tools（顶部 import 别名引用）
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
    vector_result = tools.vector_search(
        query=request.query, 
        top_k=request.top_k,                           
        device_type=request.device_type, 
        fault_code=request.fault_code,
        score_threshold=0.15
        )
    bm25_result = tools.bm25_search(
        query=request.query, 
        top_k=request.top_k,
        device_type=request.device_type, 
        fault_code=request.fault_code
        )

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

@router.post("/manual-lookup", summary="错误码录入预填检索（手册 + 工单案例）")
def manual_lookup(
    request: ManualLookupRequest,
    db: Session = Depends(get_db),
):
    """工单"错误码录入"模式预填接口：输入设备错误码/故障描述，
    返回手册标准处理（权威，带章节/页码出处）+ 相关工单案例（真实处理记录），供前端一键预填工单。"""
    from app.agents.tools import extract_error_codes, rrf_merge

    tools = _make_tools()
    error_codes = extract_error_codes(request.query)
    top_k = request.top_k

    # 1. 手册路：错误码精确匹配优先，语义检索补充
    manual_items = []
    if error_codes:
        exact = tools.manual_code_search(error_codes, top_k=top_k)
        if exact.success and exact.data:
            manual_items.extend(exact.data)
        vec = tools.manual_vector_search(request.query, top_k=top_k)
        if vec.success and vec.data:
            seen = {m.get("manual_code_id") for m in manual_items}
            for r in vec.data:
                if r.get("manual_code_id") not in seen:
                    seen.add(r.get("manual_code_id"))
                    manual_items.append(r)
    else:
        vec = tools.manual_vector_search(request.query, top_k=top_k)
        if vec.success and vec.data:
            manual_items.extend(vec.data)

    # 2. 知识库工单案例：BM25 + 向量双路召回（错误码提问会命中 fault_code/content）
    case_items = []
    try:
        bm25 = tools.bm25_search(query=request.query, top_k=top_k)
        vector = tools.vector_search(query=request.query, top_k=top_k, score_threshold=0.0)
        result_sets = [r.data for r in (bm25, vector) if r.success and r.data]
        merged = rrf_merge(result_sets, top_n=top_k) if result_sets else []
        for m in merged:
            case_items.append({
                "knowledge_id": m.get("knowledge_id") or m.get("id", 0),
                "title": m.get("title", ""),
                "content": (m.get("content", "") or "")[:300],
                "device_type": m.get("device_type", ""),
                "fault_code": m.get("fault_code", ""),
            })
    except Exception as e:
        logger.error(f"manual-lookup 知识库案例检索失败: {e}")

    # 3. 手册条目转输出（带出处字段）
    out_manual = []
    for m in manual_items:
        out_manual.append({
            "manual_code_id": m.get("manual_code_id"),
            "error_code": m.get("error_code", ""),
            "title": m.get("title", ""),
            "description": m.get("description", "") or "",
            "causes": m.get("causes", "") or "",
            "solutions": m.get("solutions", "") or "",
            "manual_name": m.get("manual_name", ""),
            "chapter": m.get("chapter", ""),
            "page": m.get("page", ""),
            "device_type": m.get("device_type", ""),
        })

    return {
        "query": request.query,
        "error_codes": error_codes,
        "manual_items": out_manual,
        "case_items": case_items,
    }


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

        # 走 LangGraph 主图 + 子图：意图路由（聊天/库存/故障）→ 对应子图执行。
        # 行为与旧 if-else 流程一致，聊天/库存不再空跑一轮检索。
        from app.agents.qa_graph import invoke_qa
        try:
            state = await asyncio.to_thread(
                invoke_qa,
                request.question, request.device_type, request.fault_code, request.top_k,
            )
        except Exception as e:
            logger.error(f"[Answer] 智能问答图执行失败: {e}")
            yield f"data: {json_module.dumps({'type': 'answer', 'content': f'服务异常: {e}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        kind = state.get("kind", "fault")
        payload = state.get("payload")

        # ---- 库存子图：一次性文本回答 ----
        if kind == "inventory":
            answer_text = getattr(payload, "answer", None) if payload is not None else None
            if not answer_text:
                answer_text = "库存查询服务暂时不可用，请稍后重试。"
            yield f"data: {json_module.dumps({'type': 'answer', 'content': answer_text}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        # ---- 聊天子图：问候/功能介绍，一次性文本回答 ----
        if kind == "chat":
            yield f"data: {json_module.dumps({'type': 'answer', 'content': payload or ''}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        # ---- 故障子图：复合故障提示 → 参考案例 → 流式生成 ----
        if state.get("suggest_expert"):
            yield f"data: {json_module.dumps({'type': 'suggest_expert'}, ensure_ascii=False)}\n\n"

        cases = (payload or {}).get("cases") or []
        references = [_to_reference(ref) for ref in cases[:8]]
        yield f"event: references\ndata: {json_module.dumps(references, ensure_ascii=False)}\n\n"

        try:
            for sse_msg in answer_agent.stream_answer(request.question, cases):
                yield sse_msg
        except Exception as e:
            logger.error(f"流式生成失败: {e}")
            yield f"data: {json_module.dumps({'type': 'answer', 'content': f'生成失败: {e}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': len(references)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/answer/expert", summary="专家问答（流式 SSE）— 多故障拆解 + ReAct 智能检索 + 生成式回答")
async def expert_answer_stream(
    request: AnswerRequest,
    db: Session = Depends(get_db),
):
    """
    专家模式：复合故障问题支持拆解 + 分组并行检索 + 分组回答。

    - 单一故障：ReAct Agent 多轮智能检索 → AnswerAgent 五段式分析
    - 多故障：LLM 拆解为单故障子查询 → 各子查询并行 ReAct 检索 → 按故障分组流式回答

    事件类型与 /answer/stream 一致，参考案例带 fault 字段标明归属故障：
    - {"type": "thinking"} — AI 正在检索分析中
    - event: references — 参考案例列表（多故障时带 fault）
    - {"type": "answer", "content": "..."} — 片段内容
    - {"type": "done", "confidence": 0.8, "sources_count": 3} — 完成
    """
    import json as json_module

    async def stream():
        yield f"data: {json_module.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        # Step 0: 库存查询前置（与普通问答保持一致）
        if answer_agent.is_inventory_query(request.question):
            from app.models.spare_part import SparePart
            result = answer_agent.handle_inventory_query(request.question, db)
            yield f"data: {json_module.dumps({'type': 'answer', 'content': result.answer}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        tools = _make_tools()

        # Step 1: 复合问题拆解（规则预检 + LLM 拆解，单故障直通）
        try:
            sub_queries = await asyncio.wait_for(
                asyncio.to_thread(fault_decomposer.decompose, request.question),
                timeout=20,            # 拆解超时 20s → 按单故障处理，不让用户干等
            )
        except asyncio.TimeoutError:
            logger.warning(f"[Expert] 问题拆解超时，按单故障处理: {request.question[:50]}")
            sub_queries = [request.question]
        sub_queries = sub_queries or [request.question]

        # ===== 多故障：分组并行 ReAct 检索 + 分组回答 =====
        if len(sub_queries) > 1:
            try:
                per_fault_results = await asyncio.wait_for(
                    asyncio.gather(*[
                        asyncio.to_thread(
                            _run_agent_search, tools, sq,
                            request.device_type, request.fault_code, request.top_k,
                            True,  # require_hybrid=True：首轮强制 vector+BM25 双路
                        )
                        for sq in sub_queries
                    ]),
                    timeout=90,        # 并行检索整体超时 90s，超时降级为"未检索到"而不是挂死
                )
            except asyncio.TimeoutError:
                logger.error("[Expert] 多故障并行检索超时，本次返回空结果")
                per_fault_results = [[] for _ in sub_queries]
            except Exception as e:
                logger.error(f"[Expert] 多故障并行检索失败: {e}")
                per_fault_results = [[] for _ in sub_queries]

            faults = []
            references = []
            for sq, res in zip(sub_queries, per_fault_results):
                device, kws = _extract_device_and_fault(tools, sq)
                cases = _filter_rerank_cases(tools, res, sq,
                                             require_device=device, require_keywords=tuple(kws))
                faults.append({"name": sq, "cases": cases})
                for ref in cases:
                    references.append(_to_reference(ref, fault=sq))
            # 参考案例跨故障全局按匹配度降序（高匹配度在上面，故障标签仍保留）
            references.sort(key=lambda x: x.get("score", 0), reverse=True)
            references = references[:8]

            yield f"event: references\ndata: {json_module.dumps(references, ensure_ascii=False)}\n\n"

            try:
                for sse_msg in answer_agent.stream_answer_multi(request.question, faults):
                    yield sse_msg
            except Exception as e:
                logger.error(f"[Expert] 多故障流式生成失败: {e}")
                yield f"data: {json_module.dumps({'type': 'answer', 'content': f'生成失败: {e}'}, ensure_ascii=False)}\n\n"
                yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': len(references)}, ensure_ascii=False)}\n\n"
            return

        # ===== 单故障：ReAct 智能检索（强制混合）+ 五段式分析回答 =====
        merged = []
        try:
            merged = await asyncio.wait_for(
                asyncio.to_thread(_run_agent_search, tools, sub_queries[0],
                                  request.device_type, request.fault_code, request.top_k,
                                  True),  # require_hybrid=True：首轮强制 vector+BM25 双路
                timeout=60,            # 单故障 ReAct 检索超时 60s
            )
        except asyncio.TimeoutError:
            logger.error("[Expert] 单故障 ReAct 检索超时")
            merged = []
        except Exception as e:
            logger.error(f"[Expert] ReAct 智能检索失败: {e}")
            merged = []

        device, kws = _extract_device_and_fault(tools, sub_queries[0])
        filtered_merged = _filter_rerank_cases(tools, merged, request.question,
                                               require_device=device, require_keywords=tuple(kws))
        references = [_to_reference(ref) for ref in filtered_merged[:8]]
        yield f"event: references\ndata: {json_module.dumps(references, ensure_ascii=False)}\n\n"

        try:
            for sse_msg in answer_agent.stream_answer(request.question, filtered_merged):
                yield sse_msg
        except Exception as e:
            logger.error(f"[Expert] 流式生成失败: {e}")
            yield f"data: {json_module.dumps({'type': 'answer', 'content': f'生成失败: {e}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': len(references)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ==================== 专家模式内部工具 ====================

def _run_agent_search(tools: RetrievalTools, query: str, device_type: Optional[str],
                      fault_code: Optional[str], top_k: int,
                      require_hybrid: bool = False) -> List[dict]:
    """在独立线程中执行一次 ReAct Agent 检索（供多故障并行调用）"""
    agent = RetrievalAssistantAgent(tools=tools)
    result = agent.search(
        query=query,
        device_type=device_type,
        fault_code=fault_code,
        max_results=top_k,
        require_hybrid=require_hybrid,
    )
    return result.results


def _to_reference(ref: dict, fault: str = "") -> dict:
    """把检索结果转为前端参考案例格式；手册条目带 source_type + 出处字段，多故障时带 fault 归属标签"""
    is_manual = ref.get("manual_code_id") is not None
    item = {
        "knowledge_id": ref.get("knowledge_id") or ref.get("manual_code_id") or ref.get("id", 0),
        "source_type": "MANUAL" if is_manual else "CASE",   # 来源类型：手册 / 工单案例
        "title": ref.get("title", ""),
        "content": (ref.get("content", "") or "")[:200],
        "device_type": ref.get("device_type", ""),
        "fault_code": ref.get("fault_code", ""),
        "score": ref.get("score", 0),
        "summary": ref.get("summary", ""),
    }
    # 手册条目出处：错误码 + 手册名 + 章节 + 页码（前端展示/回溯用）
    if is_manual:
        item["error_code"] = ref.get("error_code", "")
        item["manual_name"] = ref.get("manual_name", "")
        item["chapter"] = ref.get("chapter", "")
        item["page"] = ref.get("page", "")
    if fault:
        item["fault"] = fault
    return item


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
