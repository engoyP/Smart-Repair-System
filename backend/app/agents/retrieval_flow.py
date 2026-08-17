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
- filter_rerank_cases(): 粗筛 → 模型精排（Qwen3-Reranker）/规则降级 → 严格过滤 → 错误码置顶 → 取前 N 条

降级策略（企业级）：
- 推理服务不可用（向量路全失败）→ 检索降级 BM25-only，粗筛跳过分数阈值（无向量分可依）
- Reranker 不可用 → 回退规则重排 weighted_rerank
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from loguru import logger

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.vector_store import vector_store
from app.core.embeddings import encode_text
from app.core.reranker import rerank_cases
from app.agents.tools import (
    RetrievalTools,
    rrf_merge,
    weighted_rerank,
    extract_error_codes,
    clean_query_for_retrieval,
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
    top_k: Optional[int] = None,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
) -> Tuple[List[dict], List[str], RetrievalTools]:
    """双库检索：知识库（vector + BM25）+ 手册错误码路（精确 + 语义）→ RRF 融合

    向量路失败（推理服务不可用）时自动降级 BM25-only：结果全部为 rrf_only 标记，
    由 filter_rerank_cases 识别并跳过分数阈值。

    Args:
        top_k: 各路召回条数（默认 settings.RECALL_TOP_K），RRF 融合后候选池同值

    Returns:
        (merged, error_codes, tools): RRF 融合结果 / 识别出的错误码 / 检索工具集
    """
    top_k = top_k or settings.RECALL_TOP_K
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
    elif bm25_result.success and bm25_result.data:
        logger.warning("[RetrievalFlow] 向量路不可用（推理服务异常），检索降级为 BM25-only")
    if bm25_result.success and bm25_result.data:
        result_sets.append(bm25_result.data)

    # 错误码双路：手册精确匹配（最高优先级）+ 手册语义检索
    if error_codes:
        logger.info(f"[RetrievalFlow] 检测到错误码 {error_codes}，启用双库检索（手册 + 知识库）")
        manual_exact = tools.manual_code_search(error_codes, device_type=device_type, top_k=10)
        if manual_exact.success and manual_exact.data:
            result_sets.append(manual_exact.data)
        manual_vec = tools.manual_vector_search(query, top_k=10, device_type=device_type)
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


def _rerank_or_fallback(tools: RetrievalTools, filtered: List[dict], query: str) -> List[dict]:
    """模型精排（Qwen3-Reranker），不可用时回退规则重排 weighted_rerank

    只排序、不过滤：过滤由调用方的向量相似度阈值 + 严格过滤负责。
    """
    if settings.RERANKER_ENABLED and len(filtered) > 1:
        # 只对候选集头部做模型打分（CPU 延迟预算内），尾部保持原序
        head, tail = filtered[: settings.RERANKER_CANDIDATES], filtered[settings.RERANKER_CANDIDATES:]
        reranked = rerank_cases(head, query)
        if reranked is not None:
            return reranked + tail
        logger.warning("[RetrievalFlow] Reranker 不可用，回退规则重排 weighted_rerank")
    cleaned_q = tools.query_extractor.extract(query, use_llm_fallback=False)
    return weighted_rerank(filtered, query,
                           fault_weight=0.4, device_penalty=0.15,
                           cleaned_query=cleaned_q)


def _sort_key(m: dict) -> float:
    """排序键：模型精排分 > 向量相似度 > RRF 名次分（降级路径）"""
    if m.get("rerank_score") is not None:
        return m.get("rerank_score", 0)
    if m.get("score", 0) > 0:
        return m.get("score", 0)
    return m.get("rrf_score", 0)


def rank_manual_conditions(items: List[dict], query: str) -> List[dict]:
    """按日志/提问中的伴随信号对手册条目的 conditions 重排（不改变条目间顺序）

    对每个手册条目（含 conditions 字段），用 clean_query_for_retrieval 的技术 token
    与各 condition.signal 做子串命中计数：命中 >0 的情形排前，signal 前加 [命中] 标记，
    item['matched_signals'] 记录命中 token（供前端勾选预选与 answer_agent 标注）。
    无 conditions / 无命中的条目原样返回。

    确定性纯规则匹配（无 LLM、零延迟），与系统白名单优先风格一致。
    """
    if not items:
        return items
    tokens = [t for t in clean_query_for_retrieval(query).split() if len(t) >= 2]
    if not tokens:
        return items

    for item in items:
        conditions = item.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            continue
        matched = []
        for c in conditions:
            if not isinstance(c, dict):
                continue
            signal = str(c.get("signal") or "")
            hits = [t for t in tokens if t in signal]
            c["_hit_count"] = len(hits)
            if hits:
                matched.extend(hits)
                c["_hit_tokens"] = hits
        if matched:
            # 命中情形排前（稳定排序：命中数降序，原顺序保持）
            item["conditions"] = sorted(
                conditions,
                key=lambda c: -(c.get("_hit_count", 0) if isinstance(c, dict) else 0),
            )
            item["matched_signals"] = sorted(set(matched))
            # [命中] 标记：供前端与 LLM 识别；清理内部键防泄漏
            for c in item["conditions"]:
                if isinstance(c, dict) and c.get("_hit_count", 0) > 0:
                    c["signal"] = f"[命中] {c['signal']}"
                c.pop("_hit_count", None)
                c.pop("_hit_tokens", None)
    return items


def filter_rerank_cases(
    tools: RetrievalTools,
    merged: List[dict],
    query: str,
    top_n: Optional[int] = None,
    require_device: str = "",
    require_keywords: tuple = (),
    error_codes: Optional[List[str]] = None,
) -> List[dict]:
    """粗筛 → 精排 → 严格过滤 → 错误码置顶 → 取前 N 条

    Args:
        top_n: 最终返回条数（默认 settings.FINAL_TOP_N=10）
        require_device: 非空时，案例 device_type 必须精确匹配该设备（剔除跨设备案例）
        require_keywords: 非空时，案例 title/content/error_code 必须命中至少一个故障词
        error_codes: 非空时，手册错误码精确命中条目（manual_code_exact）置顶

    降级模式：merged 全部为 rrf_only（向量路不可用，纯 BM25）时跳过
    0.15 分数阈值——没有向量分可依，按 RRF 名次排序后走严格过滤。
    """
    top_n = top_n or settings.FINAL_TOP_N
    bm25_only_degraded = bool(merged) and all(m.get("rrf_only", False) for m in merged)

    if bm25_only_degraded:
        # 推理服务不可用：纯 BM25 降级，按 RRF 名次排序
        filtered = sorted(merged, key=lambda x: x.get("rrf_score", 0), reverse=True)
        logger.warning("[RetrievalFlow] BM25-only 降级模式：跳过向量分数阈值，按 RRF 名次排序")
    else:
        filtered = [m for m in merged if not m.get("rrf_only", False) and m.get("score", 0) >= settings.RETRIEVAL_COARSE_THRESHOLD]
        if filtered:
            filtered = _rerank_or_fallback(tools, filtered, query)

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

    strict.sort(key=_sort_key, reverse=True)

    # 错误码精确命中（手册权威标准处理）置顶：RRF 只按名次融合，exact 单路名次吃亏
    if error_codes:
        strict.sort(key=lambda x: (
            0 if x.get("method") == "manual_code_exact" else 1,
            -_sort_key(x),
        ))

    # 手册条目情形排序：按日志/提问中的伴随信号匹配度重排 conditions（三路返回统一生效）
    strict = rank_manual_conditions(strict, query)

    if used_fallback:
        return strict[:top_n]   # 兜底分支已通过初始过滤，不再二次过滤（重排可能压低分数）
    if bm25_only_degraded:
        return strict[:top_n]   # 降级模式无向量分，不做 0.15 二次过滤
    return [m for m in strict if m.get("score", 0) >= settings.RETRIEVAL_COARSE_THRESHOLD][:top_n]
