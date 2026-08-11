"""公共检索编排层：双库检索 + RRF 融合 + 过滤重排（唯一实现）

供以下入口复用，避免"检索逻辑写多遍"导致策略漂移：
- 智能问答 LangGraph（qa_graph.py FaultQaSubgraph）
- 钉钉机器人 / MCP 知识检索（mcp/tools.py search_knowledge）
- 专家模式（search.py /answer/expert 的检索/过滤）
- 历史遗留端点（search.py quick / hybrid / agent / manual-lookup）

统一封装：
- make_tools(): 构造检索工具集
- retrieve_hybrid(): 知识库（vector+BM25）+ 手册错误码路（精确+语义）→ RRF 融合
- extract_device_and_fault(): 从查询提取设备类型 + 故障关键词
- filter_rerank_cases(): 过滤/重排/严格匹配/错误码置顶 → 取前 N 条
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from loguru import logger

from app.core.database import SessionLocal
from app.core.vector_store import vector_store
from app.core.embeddings import encode_text
from app.agents.tools import (
    RetrievalTools,
    rrf_merge,
    weighted_rerank,
    extract_error_codes,
    _DEVICE_TYPE_TERMS,
)


def make_tools() -> RetrievalTools:
    """构造检索工具集（单一入口，避免各处重复 new）"""
    return RetrievalTools(
        db_session_factory=SessionLocal,
        vector_store=vector_store,
        embedding_fn=encode_text,
    )


def retrieve_hybrid(
    query: str,
    top_k: int = 10,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
) -> Tuple[List[dict], List[str], RetrievalTools]:
    """双库检索：知识库（vector + BM25）+ 手册错误码路（精确 + 语义）→ RRF 融合

    Returns:
        (merged, error_codes, tools): RRF 融合结果 / 识别出的错误码 / 检索工具集
    """
    tools = make_tools()
    error_codes = extract_error_codes(query)
    result_sets = []

    vector_result = tools.vector_search(
        query=query, top_k=top_k, device_type=device_type,
        fault_code=fault_code, score_threshold=0.0,
    )
    bm25_result = tools.bm25_search(
        query=query, top_k=top_k, device_type=device_type, fault_code=fault_code,
    )
    if vector_result.success and vector_result.data:
        result_sets.append(vector_result.data)
    if bm25_result.success and bm25_result.data:
        result_sets.append(bm25_result.data)

    # 错误码双路：手册精确匹配（最高优先级）+ 手册语义检索
    if error_codes:
        logger.info(f"[RetrievalFlow] 检测到错误码 {error_codes}，启用双库检索（手册 + 知识库）")
        manual_exact = tools.manual_code_search(error_codes, device_type=device_type, top_k=5)
        if manual_exact.success and manual_exact.data:
            result_sets.append(manual_exact.data)
        manual_vec = tools.manual_vector_search(query, top_k=5, device_type=device_type)
        if manual_vec.success and manual_vec.data:
            result_sets.append(manual_vec.data)

    merged = rrf_merge(result_sets, top_n=top_k) if result_sets else []
    return merged, error_codes, tools


def extract_device_and_fault(tools: RetrievalTools, query: str) -> Tuple[str, List[str]]:
    """从查询中提取设备类型 + 故障关键词（供检索结果过滤使用）

    Returns:
        (device, keywords): 设备类型（可能为空）+ 故障关键词列表
    """
    cleaned = tools.query_extractor.extract(query, use_llm_fallback=False)
    # 最长设备词优先匹配（避免"机床"吃掉"数控机床"）
    device = next((t for t in sorted(_DEVICE_TYPE_TERMS, key=len, reverse=True) if t and t in cleaned), "")
    keywords = []
    for w in cleaned.split():
        w = w.strip()
        if not w or len(w) < 2:
            continue
        if w in _DEVICE_TYPE_TERMS:   # 设备词全部从关键词里剔除
            continue
        keywords.append(w)
    return device, keywords


def filter_rerank_cases(
    tools: RetrievalTools,
    merged: List[dict],
    query: str,
    top_n: int = 8,
    require_device: str = "",
    require_keywords: tuple = (),
    error_codes: Optional[List[str]] = None,
) -> List[dict]:
    """过滤 rrf_only/低分 → 加权重排 → 设备/故障关键词严格过滤 → 错误码置顶 → 取前 N 条

    Args:
        require_device: 非空时，案例 device_type 必须精确匹配该设备（剔除跨设备案例）
        require_keywords: 非空时，案例 title/content/error_code 必须命中至少一个故障词
        error_codes: 非空时，手册错误码精确命中条目（manual_code_exact）置顶
    """
    filtered = [m for m in merged if not m.get("rrf_only", False) and m.get("score", 0) >= 0.15]
    if filtered:
        cleaned_q = tools.query_extractor.extract(query, use_llm_fallback=False)
        filtered = weighted_rerank(filtered, query,
                                   fault_weight=0.4, device_penalty=0.15,
                                   cleaned_query=cleaned_q)

    # 严格过滤：设备匹配 + 故障关键词命中
    strict = filtered
    used_fallback = False
    if require_device or require_keywords:
        # 关键词命中范围：标题 + 正文 + 错误码（手册条目正文不含错误码本身，必须纳入 error_code 字段）
        def _searchable(m: dict) -> str:
            text = f"{m.get('title', '')} {m.get('content', '')}"
            if m.get("error_code"):
                text += f" {m.get('error_code')}"
            return text

        strict = [
            m for m in filtered
            if (not require_device or m.get("device_type") == require_device)
            and (not require_keywords or any(k in _searchable(m) for k in require_keywords))
        ]
        # 兜底：严格过滤后为空则回退到宽松过滤的 top2，避免误伤导致"未检索到"
        if not strict:
            strict = filtered[:2]
            used_fallback = True

    strict.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 错误码精确命中（手册权威标准处理）置顶：RRF 只按名次融合，exact 单路名次吃亏
    if error_codes:
        strict.sort(key=lambda x: (
            0 if x.get("method") == "manual_code_exact" else 1,
            -x.get("score", 0),
        ))

    if used_fallback:
        return strict[:top_n]   # 兜底分支已通过初始 0.15 过滤，不再二次过滤（重排可能压低分数）
    return [m for m in strict if m.get("score", 0) >= 0.15][:top_n]
