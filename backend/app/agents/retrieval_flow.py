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
  （严格过滤后为空则返回空，不做跨设备兜底，由回答层如实说未检索到）

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
    get_device_terms,
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
    # 设备词全集（静态内置词 + 知识库实际设备）；最长词优先匹配（避免“CNC”吃掉“CNC加工中心”）
    device_terms = get_device_terms()
    device = next((t for t in sorted(device_terms, key=len, reverse=True) if t and t in cleaned), "")
    keywords = []
    for w in cleaned.split():
        w = w.strip()
        if not w or len(w) < 2:
            continue
        if w in device_terms:   # 设备词全部从关键词里剔除
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
    item['matched_signals'] 记录命中 token（供前端勾选预选与 answer_generator 标注）。
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
    # 过滤后为空则返回空——不做“塞两条宽松结果”兜底：测试证明兜底塞的 100% 是跨设备噪声，
    # 伪装成结果流入回答层是串味回答的来源；由回答层的空案例/低分护栏如实说未检索到
    strict = filtered
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
        if not strict:
            logger.info(f"[RetrievalFlow] 严格过滤后无候选（设备={require_device!r} 关键词={list(require_keywords)}），返回空结果")

    strict.sort(key=_sort_key, reverse=True)

    # 错误码精确命中（手册权威标准处理）置顶：RRF 只按名次融合，exact 单路名次吃亏
    if error_codes:
        strict.sort(key=lambda x: (
            0 if x.get("method") == "manual_code_exact" else 1,
            -_sort_key(x),
        ))

    # 手册条目情形排序：按日志/提问中的伴随信号匹配度重排 conditions（三路返回统一生效）
    strict = rank_manual_conditions(strict, query)

    if bm25_only_degraded:
        return strict[:top_n]   # 降级模式无向量分，不做 0.15 二次过滤
    return [m for m in strict if m.get("score", 0) >= settings.RETRIEVAL_COARSE_THRESHOLD][:top_n]


def evaluate_retrieval_quality(results: List[dict]) -> dict:
    """检索结果质量阀门（规则判断，零 LLM）——ReAct / 专家救援 / 公共编排层复用的一套判定

    达标条件：≥3条 且（≥2条高分≥0.6 或 最高分≥0.7）。否则视为不足。

    Returns:
        {"sufficient": bool, "reason": str, "count": int, "max_score": float}
    """
    if not results:
        return {"sufficient": False, "reason": "无结果", "count": 0, "max_score": 0.0}
    high = sum(1 for r in results if r.get("score", 0) >= settings.AGENT_QUALITY_HIGH_SCORE)
    max_score = max((r.get("score", 0) for r in results), default=0.0)
    if len(results) >= 3 and (high >= 2 or max_score >= settings.AGENT_QUALITY_TARGET_SCORE):
        return {"sufficient": True, "reason": f"结果充足 ({len(results)} 条, 最高分 {max_score:.2f})",
                "count": len(results), "max_score": round(max_score, 4)}
    return {"sufficient": False, "reason": f"结果不足 ({len(results)} 条, 最高分 {max_score:.2f})",
            "count": len(results), "max_score": round(max_score, 4)}


# ============================================================
# 维修意图判定（四入口统一：问答/专家/追踪/钉钉）
# ============================================================
# 第一层：纯 regex 混合型错误码（不连库，不跑白名单）
# 第二层：关键词白名单（含维修术语 + 简短应答精确匹配）
# 第三层：①②均未命中 → 必走完整检索（四路+RRF+精排）→ 看 cases 最高分
#        阈值 REPAIR_INTENT_RELEVANCE_THRESHOLD=0.4 以下 → 最终判无关

_REPAIR_RELATED_KEYWORDS = (
    # 设备大类（项目实际设备表 8 大类 + 常见别名缩写）
    "注塑机", "数控", "机床", "液压", "传送带", "空压机", "压缩机", "变压器", "电机",
    "电动机", "锅炉", "制冷", "机器人", "PLC", "传感器", "继电器", "变频器", "伺服",
    "驱动器", "主轴", "刀库", "轴承", "齿轮", "油泵", "水泵", "气泵", "马达", "气缸",
    "油缸", "阀门", "开关", "电源", "线路", "电路", "主板", "屏幕", "电池", "设备",
    "机组", "机器", "装置", "密封圈", "滤芯", "皮带", "链条",
    # 项目实际设备型号与别名
    "CNC", "cnc", "加工中心", "CNC车床", "CNC加工中心", "数控车床", "数控折弯机",
    "冲床", "折弯机", "激光切割机", "线切割", "磨床", "车床", "铣床",
    # 设备部件/通用词
    "X轴", "Y轴", "Z轴", "刀塔", "尾座", "卡盘", "滑块", "送料", "导轨",
    "定位", "尺寸", "加工", "切割", "冲压", "车削", "磨削", "螺纹", "表面",
    # 故障现象（常见）
    "温度", "压力", "电压", "电流", "报警", "异响", "振动", "漏油", "漏水", "死机",
    "黑屏", "不转", "不启动", "跳闸", "过热", "过载", "堵塞", "卡死", "断电", "短路",
    "故障", "坏了", "异常", "无响应", "停机", "不工作", "松动", "磨损", "烧毁", "冒烟",
    "异味", "抖动", "卡顿", "闪退", "失灵", "渗油", "红灯",
    # 尺寸/精度类（机加工常见）
    "偏差", "超差", "偏", "偏大", "偏小", "不对", "不准", "不稳", "不稳定",
    "变形", "划伤", "划痕", "毛刺", "飞边", "粗糙度", "纹路", "振纹",
    "掉刀", "乱牙", "乱扣", "不到位", "拉刀", "拉毛", "糊", "糊了",
    # 排查操作反馈
    "检查", "正常", "更换", "清理", "调整", "测试", "开机", "重启", "好了", "解决",
    "试机", "运行", "恢复", "排除", "确认", "测量", "紧固", "校正", "运转", "复位",
    "清洗", "加油", "换油", "拆卸", "安装",
    # 排查操作口语
    "排查", "怎么办", "怎么修", "怎么处理", "怎么回事", "原因", "修一下",
)

# 短应答词（仅精确匹配，防"你好"被"好"子串误命中）
_SHORT_ACK_WORDS = (
    "嗯", "好", "好的", "行", "可以", "继续", "然后", "下一步", "接下来", "对",
    "是的", "ok", "OK", "试过了", "查了", "拆了", "装了", "换了", "清了", "加了",
    "检查了",
)


def _extract_error_codes_fast(message: str) -> List[str]:
    """第一层：纯 regex 提取混合型错误码（不连 DB 白名单，零外部依赖）
    只抓字母+数字混合 token（SV0436 / ALM-6401 / E3091 / PS0002）。
    纯数字 4~6 位报警码在第三步检索里兜底（连库白名单）。"""
    import re as _re
    if not message:
        return []
    tok_re = _re.compile(r"[A-Za-z]+[\dA-Za-z]+(?:[\s-][\dA-Za-z]+)?")
    codes = []
    for m in tok_re.finditer(message):
        tok = _re.sub(r'[\s-]', '', m.group(0)).upper()
        if len(tok) >= 3 and not tok.isdigit() and any(c.isdigit() for c in tok):
            codes.append(tok)
    return codes


def repair_intent_fast_check(message: str) -> dict:
    """维修意图快速判定（零外部依赖）：第一层 regex 错误码 + 第二层关键词。

    Returns:
        {"decision": "related" | "check" | "irrelevant",
         "by": "error_code" | "keywords" | "ack" | "short_irrelevant" | "need_retrieval",
         "error_codes": [...]}
    """
    text = (message or "").strip()
    if not text:
        return {"decision": "irrelevant", "by": "empty", "error_codes": []}

    # 第一层：regex 错误码（纯 regex，零依赖）
    ec = _extract_error_codes_fast(text)
    if ec:
        return {"decision": "related", "by": "error_code", "error_codes": ec}

    # 第二层：维修关键词白名单（子串匹配 —— 故障词/设备名）
    if any(kw in text for kw in _REPAIR_RELATED_KEYWORDS):
        return {"decision": "related", "by": "keywords", "error_codes": []}

    # 第二层补充：简短应答词（≤4字，精确匹配，防单字子串误伤）
    if len(text) <= 4 and text in _SHORT_ACK_WORDS:
        return {"decision": "related", "by": "ack", "error_codes": []}

    # 7 字以内未命中任何关键词/应答词/错误码 → 直接判无关省检索（典型闲聊如"今天天气不错/帮我查工资/老板周末加班"都 6~7 字）
    if len(text) <= 7:
        return {"decision": "irrelevant", "by": "short_irrelevant", "error_codes": []}

    # 其他：①②全不命中（长度≥8且无关键词）→ 进入第三层检索判定
    return {"decision": "check", "by": "need_retrieval", "error_codes": []}


# 最终判定为"与维修无关"时的统一护栏回复文案（四入口共用）
REPAIR_IRRELEVANT_REPLY = (
    "这条消息和设备维修无关，我先不继续处理。\n"
    "如果是设备故障，请描述具体的设备和故障现象，例如：\n"
    "注塑机温度过高、空压机不启动、CNC 主轴 SV0436 报警。"
)


def repair_intent_check(message: str,
                        tools: object,
                        device_type: str = "",
                        threshold: Optional[float] = None,
                        top_k: int = 5,
                        ) -> dict:
    """三层完整维修意图判定：①regex 错误码 → ②关键词 → ③检索打分
    任何一层命中即放行（decision=related）；
    ①②未命中→跑检索：cases 空或 max_score < threshold → decision=irrelevant

    Args:
        message: 用户消息
        tools: retrieval_flow.make_tools() 构造的工具上下文
        device_type: 已知设备类型（传进检索）
        threshold: 第三层"相关"判定阈值，默认 RETRIEVAL_COARSE_THRESHOLD/2 ≈ 0.35
        top_k: 第三层检索取的候选数

    Returns:
        {"decision": "related"|"irrelevant",
         "by": "error_code"|"keywords"|"ack"|"retrieval_hit"|"retrieval_empty",
         "cases": [...],                  # 已过滤精排的 cases，调用方可直接复用不用再检索
         "max_score": float,
         "error_codes": [...]}
    """
    if threshold is None:
        threshold = max(0.35, settings.RETRIEVAL_COARSE_THRESHOLD)

    # ①② 快路径
    fast = repair_intent_fast_check(message)
    if fast["decision"] == "related":
        # 放行：按正常流程跑一次 retrieve_hybrid + filter_rerank_cases，把 cases 返回给调用方复用
        merged, err_codes, _ = retrieve_hybrid(message, top_k=top_k * 2, device_type=device_type)
        dev, kws = extract_device_and_fault(tools, message)
        cases = filter_rerank_cases(
            tools, merged, message, top_n=top_k,
            require_device=dev, require_keywords=tuple(kws), error_codes=err_codes,
        )
        # 严格过滤空：宽松降级（不传 device/kws）只传错误码置顶
        if not cases:
            cases = filter_rerank_cases(tools, merged, message, top_n=top_k, error_codes=err_codes)
        ms = max((c.get("score", 0) for c in cases), default=0.0)
        return {"decision": "related", "by": fast["by"], "cases": cases,
                "max_score": ms, "error_codes": err_codes}
    if fast["decision"] == "irrelevant":
        return {"decision": "irrelevant", "by": fast["by"], "cases": [],
                "max_score": 0.0, "error_codes": fast.get("error_codes", [])}

    # 第三层：①②都没底 → 走检索路线（切词→向量化→四路召回→RRF→精排）
    merged, err_codes, _ = retrieve_hybrid(message, top_k=top_k * 2, device_type=device_type)
    dev, kws = extract_device_and_fault(tools, message)
    cases = filter_rerank_cases(
        tools, merged, message, top_n=top_k,
        require_device=dev, require_keywords=tuple(kws), error_codes=err_codes,
    )
    if not cases:
        # 严格过滤空时给宽松版本一次机会（只传错误码置顶），再判空
        cases = filter_rerank_cases(tools, merged, message, top_n=top_k, error_codes=err_codes)
    max_score = max((c.get("score", 0) for c in cases), default=0.0)
    if cases and max_score >= threshold:
        return {"decision": "related", "by": "retrieval_hit", "cases": cases,
                "max_score": max_score, "error_codes": err_codes}
    return {"decision": "irrelevant", "by": "retrieval_empty", "cases": cases,
            "max_score": max_score, "error_codes": err_codes}
