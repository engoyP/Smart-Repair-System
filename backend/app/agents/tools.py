"""检索工具集 - 向量检索 / BM25 关键词检索 / 条件查询 / RRF 融合 / 查询改写"""
import json
import re
from typing import List, Dict, Optional, Callable, Any, Set, Tuple
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class ToolResult:
    """工具调用结果"""
    success: bool
    data: Any
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


# ==================== 加权评分：设备类型 vs 故障原因 ====================

# 设备类型关键词集合（匹配时权重低）
_DEVICE_TYPE_TERMS = {
    "注塑机", "数控机床", "CNC", "液压系统", "传送带", "空压机", "变压器",
    "电机", "锅炉", "制冷系统", "机器人", "输送设备", "PLC", "PLC系统",
    "机床", "设备", "机器", "机器设备",
}

# 设备类型关键词的部分匹配集（n-gram 片段）
_DEVICE_TYPE_NGRAMS = set()
for _term in _DEVICE_TYPE_TERMS:
    for _i in range(len(_term)):
        for _n in [2, 3]:
            if _i + _n <= len(_term):
                _DEVICE_TYPE_NGRAMS.add(_term[_i:_i + _n])

# 故障原因关键词（只有症状/异常描述，不含设备名/部件名）
# 设备名/部件名不是故障原因，不应参与故障匹配评分
_FAULT_CAUSE_SIGNALS = {
    "故障", "异常", "报警", "失效", "损坏", "磨损", "泄漏", "堵塞", "卡死",
    "过热", "过载", "短路", "断路", "烧毁", "断裂", "变形", "腐蚀", "老化",
    "偏高", "偏低", "不稳定", "波动", "不足", "过大", "过高", "过低",
    "异响", "振动", "噪音", "漏油", "停机", "跳闸", "不转", "不动作",
    "失灵", "失效", "失控", "不回退", "无法启动", "无法加载", "无法卸载",
    "打滑", "跑偏", "爬行", "抖动", "冲击", "温度", "压力", "流量",
    "电压", "电流", "绝缘", "润滑", "冷却", "加热",
    # 常见症状词
    "指示灯", "不亮", "不工作", "死机", "黑屏", "无输出", "无响应",
    "报错", "卡住", "闪屏", "乱码", "不识别", "不启动", "断开",
    "无法连接", "无法读取", "不显示", "不运行", "没反应", "失灵",
    "不通讯", "通讯中断", "信号弱", "丢包", "延迟高",
}

# 权重配置
FAULT_CAUSE_WEIGHT = 5       # 故障原因关键词：标题权重
DEVICE_TYPE_WEIGHT = 1       # 设备类型关键词：标题权重（低）
FAULT_CONTENT_WEIGHT = 2     # 故障原因关键词：内容权重
DEVICE_CONTENT_WEIGHT = 1    # 设备类型关键词：内容权重


# ==================== 用户提问清洗：去除干扰词，保留技术关键词 ====================

# 检索时必须去除的干扰词：疑问词、请求动词、助词、通用口语词等
# 这些词与设备/故障无关，会严重干扰语义向量和关键词匹配打分
_QUERY_NOISE_WORDS = {
    # —— 疑问词 ——
    "怎么", "怎样", "如何", "什么", "为什么", "为啥", "咋", "咋办",
    "哪", "哪些", "哪里", "哪个", "几种", "多少", "几",
    "怎么办", "怎么回事", "怎么样", "怎么着", "怎么弄", "嘛", "回事",
    "哪方面", "哪些方面", "哪儿", "甚么",
    # —— 请求/动作动词 ——
    "处理", "解决", "办", "办法", "方法", "排查", "排除", "维修",
    "看", "看看", "查看", "查查", "查一下", "查询", "检索", "搜索",
    "帮", "帮助", "告诉我", "请教", "请问", "指导", "分析",
    "找", "找出", "推荐", "建议",
    # —— 通用口语/修饰 ——
    "一下", "了", "的", "是", "会", "要", "能", "可以", "请",
    "吗", "呢", "吧", "啊", "哦", "嗯", "哈", "呗", "啦", "哟",
    "我", "你", "他", "我们", "你们", "他们", "咱", "咱们",
    "这个", "那个", "这", "那", "现在", "最近", "已经", "目前", "当前",
    "问题", "情况", "现象", "事儿", "东西", "样子", "原因",
    "总是", "经常", "频繁", "突然", "刚", "刚刚", "老是", "可能", "也许",
    # —— 前缀/后缀动词 ——
    "出现", "发生", "产生", "引起", "导致", "造成", "提示", "显示",
    "报出", "给出", "导致",
    # —— 设备/故障动词前缀 ——
    "报",  # "PLC报RAM错误" 中 "报" 是动词，应去掉
    "有",  # "有异响" → 只保留"异响"
    "出",  # "出问题" → "问题"也是干扰词，双删
    "跳",  # "跳闸"整体是固定词保护，但单字"跳"是干扰
    # —— 连接/连词（容易在末尾残留）——
    "和", "与", "或", "及", "以及", "或者", "还有", "还是",
    # —— 推测/估计类（用户加的"可能、大概"，严重影响向量语义匹配）——
    "可能", "也许", "或许", "大概", "应该", "恐怕", "估计", "猜测",
    "会不会", "是否", "是不是", "能否", "能不能", "可不可以",
    "是不是", "有没有", "有无", "能不",
    # —— 方面/角度/类别词 ——
    "方面", "层面", "角度", "类别", "类型", "方向",
    # —— 定位/限定前缀（常见口语"这台设备""关于液压"等）——
    "这台", "那台", "这条", "那条", "这个", "那个", "这些", "那些",
    "我的", "你的", "他的", "咱们的",
    "关于", "有关", "对于", "至于", "针对", "就", "论",
    "台",  # "这台"的"台"（前缀剥离时会配合"这/那"去掉，但单独剥离需要）
    # —— 观点/主观动词（"你认为""我觉得"等）——
    "认为", "觉得", "想", "猜测", "估计", "怀疑",
    # —— 设备限定词（"设备PLC"里的"设备"其实是冗余，但保留"设备"也无大害 → 这里不列入以免误伤"设备类型"字段）
    #     但"现在设备"里的"设备"后跟PLC时，用户常说"现在设备X有Y故障"
    #     → 这里保持中性，不强行删，留给向量自行处理
    # —— 其他容易残留的口语词 ——
    "啊哈", "呢啊", "嘛呢",
    "之类", "等等", "什么的", "啥的",
}

# 不能按单字去掉的故障固定词（防止误删）
_PRESERVED_FAULT_TERMS = {
    "跳闸", "报错", "报警", "抖动", "异响", "卡死", "打滑", "跑偏",
    "停机", "漏油", "漏水", "漏气", "跳闸", "过热", "过载", "短路",
    "失控", "失灵", "死机", "黑屏", "闪屏", "乱码", "不亮", "不转",
    "不启动", "不工作", "不动作", "没反应", "无响应", "无输出",
    "不显示", "不识别", "不通讯", "通讯中断", "信号弱", "丢包",
    "延迟高", "无法连接", "无法启动", "无法加载", "无法卸载",
    "无法读取", "不回退",
}


# 中高置信度的词——即使出现在中文 span 的中间，也可以安全替换
# 判定标准：绝对不会出现在设备型号/故障码/技术术语名称里
_HIGH_CONFIDENCE_REMOVE_WORDS = {
    # —— 疑问词（即使在中间也能安全删）——
    "怎么", "怎样", "如何", "什么", "为什么", "为啥", "咋", "咋办",
    "哪些", "哪里", "哪个", "几种", "多少", "怎么办", "怎么回事",
    "怎么弄", "怎么样", "怎么着", "哪方面", "哪些方面", "哪儿", "甚么",
    # —— 推测/估计词 ——
    "可能", "也许", "或许", "大概", "应该", "恐怕", "估计", "猜测",
    "会不会", "是否", "是不是", "能否", "能不能", "可不可以", "有无",
    # —— 方面/角度/类型 ——
    "方面", "层面", "角度", "类别", "类型", "方向",
    # —— 观点/主观动词 ——
    "认为", "觉得", "想", "怀疑",
    # —— 限定/定位前缀 ——
    "这台", "那台", "这条", "那条", "这些", "那些",
    "我的", "你的", "他的", "咱们的",
    "关于", "有关", "对于", "至于", "针对",
    # —— 常见口语修饰 ——
    "现在", "最近", "目前", "当前", "已经",
    "总是", "经常", "频繁", "突然", "刚刚", "老是",
    "一下", "吗", "呢", "吧", "啊", "哦", "嗯", "呗", "啦", "哟",
    "嘛", "回事", "之类", "等等", "什么的", "啥的",
    # —— 常见结构助词（"的""是"在中文中无处不在，且绝对不会出现在设备型号/故障码/技术术语名称里）——
    "的", "是", "地", "得", "了", "着", "过",
    # —— 时间/限定残余 ——
    "还有", "还是", "以及", "或者", "以及",
    # —— 其他常见残余 ——
    "问题", "情况", "现象", "事儿", "东西", "样子", "原因",
}


def clean_query_for_retrieval(query: str) -> str:
    """清洗用户提问，去除所有非技术干扰词

    改进的清洗算法（解决中文连续span内部的干扰词漏删问题）：
      1. 去标点
      2. 保护固定故障词（跳闸/报错等）→ 占位符
      3. 拆为「中文span」和「英文/数字span」分别处理
      4. 对每个中文 span 分别做：
         a. 前缀剥离：从头部反复剥离匹配的干扰词（从长到短）
         b. 后缀剥离：从尾部反复剥离匹配的干扰词
         c. 中间替换：对疑问词（怎么/如何/什么等）即使在中间也安全替换
      5. 英文/数字 span 直接保留（通常是型号、缩写、代码）
      6. 过掉单字中文、再精确匹配一次干扰词
      7. 还原固定故障词 → 空格拼接输出
    """
    if not query:
        return ""

    import re as _re
    raw = query.strip()

    # Step 0: 去标点符号，保留空格分隔
    cleaned = _re.sub(
        r'[，。！？；：、""''（）【】《》·\s,.;:!?()\[\]<>"\'\\/\-~]+',
        ' ', raw
    ).strip()

    # Step 1: 保护固定故障词（先按长度从长到短替换为占位符）
    placeholders: Dict[str, str] = {}
    working = cleaned
    for idx, term in enumerate(sorted(_PRESERVED_FAULT_TERMS, key=len, reverse=True)):
        if term in working:
            key = f"__PF{idx}__"
            working = working.replace(term, f" {key} ")
            placeholders[key] = term

    # Step 2: 拆分为 中文块 / 英文数字块 交替
    # 注意：不立刻 split，逐段处理，保留中文 span 的连续上下文便于前/后缀剥离
    processed_chunks = []
    pos = 0
    text = working
    pattern = _re.compile(r'[\u4e00-\u9fff]+|[A-Za-z0-9_\-]+')
    for m in pattern.finditer(text):
        start, end = m.span()
        # 前面的非匹配内容丢弃（都是空格或符号）
        chunk = m.group(0)
        if _re.fullmatch(r'[\u4e00-\u9fff]+', chunk):
            cleaned_chunk = _clean_chinese_subspan(chunk)
        else:
            cleaned_chunk = chunk  # 英文/数字/型号原样保留
        if cleaned_chunk:
            processed_chunks.append(cleaned_chunk)

    # Step 3: 二次过滤：精确匹配干扰词，去掉单字中文
    final_tokens = []
    for tok in processed_chunks:
        # 还原占位符
        for key, term in placeholders.items():
            tok = tok.replace(key, term)
        # 精确匹配干扰词
        if tok in _QUERY_NOISE_WORDS:
            continue
        # 单字中文丢弃
        if _re.fullmatch(r'[\u4e00-\u9fff]', tok):
            continue
        if tok:
            final_tokens.append(tok)

    result = " ".join(final_tokens).strip()
    # 去掉可能遗留的占位符残余（无对应 term 的情况）
    result = _re.sub(r'__PF\d+__', '', result).strip()
    logger.info(f"[QueryClean] 原始: {raw} → 清洗后: {result}")
    return result


def _clean_chinese_subspan(span: str) -> str:
    """对单个连续中文字符串进行干扰词清洗
    策略：
      a) 前缀剥离（从头部反复去掉最长匹配的干扰词）
      b) 后缀剥离（从尾部反复去掉最长匹配的干扰词）
      c) 中间替换：对高置信疑问词（在技术术语中不可能出现）做内联替换
      d) 清理后若 >=2 字保留，否则丢弃
    """
    if not span:
        return ""
    # 噪声词按长度降序，保证长词优先剥离
    sorted_noise = sorted(
        (w for w in _QUERY_NOISE_WORDS if len(w) >= 1),
        key=len, reverse=True,
    )

    # (a) 前缀剥离：最多循环 10 轮防止异常
    for _ in range(10):
        changed = False
        for nw in sorted_noise:
            if len(span) > len(nw) and span.startswith(nw):
                # 确认：剥离后仍剩下 >=1 字，否则不剥离（防止词本身是技术词的前缀，虽然一般不会）
                new_span = span[len(nw):]
                if len(new_span) >= 1:
                    span = new_span
                    changed = True
                    break  # 每轮从头匹配（长词优先）
        if not changed:
            break

    # (b) 后缀剥离
    for _ in range(10):
        changed = False
        for nw in sorted_noise:
            if len(span) > len(nw) and span.endswith(nw):
                new_span = span[:-len(nw)]
                if len(new_span) >= 1:
                    span = new_span
                    changed = True
                    break
        if not changed:
            break

    # (c) 中间替换：高置信可删除词即使在中间也可以安全删（不会出现在技术术语里）
    import re as _re
    for qw in sorted(_HIGH_CONFIDENCE_REMOVE_WORDS, key=len, reverse=True):
        if qw in span:
            span = span.replace(qw, ' ')
    # 清理替换后产生的空格
    span = _re.sub(r'\s+', '', span)

    return span if len(span) >= 2 else ""


def _classify_keywords(tokens: Set[str]) -> Tuple[Set[str], Set[str]]:
    """将查询关键词分类为设备类型词和故障原因词

    Args:
        tokens: n-gram 分词后的关键词集合

    Returns:
        (device_keywords, fault_keywords): 设备类型词集合, 故障原因词集合
    """
    device_keywords = set()
    fault_keywords = set()

    for token in tokens:
        # 完整匹配设备类型
        if token in _DEVICE_TYPE_TERMS:
            device_keywords.add(token)
        # n-gram 匹配设备类型片段
        elif token in _DEVICE_TYPE_NGRAMS:
            device_keywords.add(token)
        # 匹配故障原因信号词
        elif token in _FAULT_CAUSE_SIGNALS:
            fault_keywords.add(token)
        else:
            # 默认归类为故障原因（通用词更可能是描述故障而非设备）
            fault_keywords.add(token)

    return device_keywords, fault_keywords


def weighted_rerank(
    results: List[Dict],
    query: str,
    fault_weight: float = 0.4,
    device_penalty: float = 0.15,
    cleaned_query: Optional[str] = None,
) -> List[Dict]:
    """加权重排序：阶梯式惩罚，按故障关键词命中数决定最终分数

    策略：
      1. 优先使用 cleaned_query（已提取的技术关键词）做匹配
      2. 若无 cleaned_query，则从原始 query 中提取故障信号词
      3. 两步式处理：
         - 比率 < 0.3 → ×0.15（几乎不相关）
         - 比率 ≥ 0.3 → 正常加权加分

    Args:
        results: RRF 融合后的结果列表
        query: 原始查询文本（用于 fallback）
        fault_weight: 故障原因匹配的加分系数（3+ 命中时使用）
        device_penalty: 保留参数，未使用
        cleaned_query: 已提取的技术关键词（优先使用，避免干扰词影响打分）

    Returns:
        重排序后的结果列表
    """
    if not results:
        return results

    # ===== 优先使用 cleaned_query（已提取的技术关键词）=====
    effective_query = cleaned_query or query

    # 故障原因关键词中排除过于通用的词
    _GENERIC_SIGNALS = {"故障"}

    # 设备类型关键词
    device_kw = set()
    for dev in _DEVICE_TYPE_TERMS:
        if dev in effective_query:
            device_kw.add(dev)

    # 故障关键词提取：
    # 如果有 cleaned_query（白名单提取的关键词），直接按空格拆分作为 fault_kw
    # 因为 cleaned_query 中的每个词都是白名单匹配的技术词，无需再用 _FAULT_CAUSE_SIGNALS 过滤
    fault_kw = set()
    if cleaned_query:
        for token in cleaned_query.split():
            token = token.strip()
            if token and token not in _GENERIC_SIGNALS and token not in device_kw:
                fault_kw.add(token)
    else:
        # 无 cleaned_query 时，从原始 query 中提取故障信号词
        for sig in _FAULT_CAUSE_SIGNALS:
            if sig in effective_query and sig not in _GENERIC_SIGNALS:
                fault_kw.add(sig)
        # 兜底：从中文片段中补充
        chinese_spans = re.findall(r'[\u4e00-\u9fff]+', effective_query.strip())
        if not fault_kw:
            for span in chinese_spans:
                if span not in _GENERIC_SIGNALS and len(span) >= 2:
                    fault_kw.add(span)

    if not fault_kw:
        return results  # 没有故障关键词，不需要重排

    for item in results:
        title = item.get("title", "")
        content = item.get("content", "")
        combined = title + " " + content

        # 计算条目命中查询中故障信号词的数量
        fault_hit_count = sum(1 for kw in fault_kw if kw in combined)
        fault_ratio = fault_hit_count / len(fault_kw) if fault_kw else 0

        # 设备类型匹配度（前提条件：不匹配直接压到低分）
        device_type = item.get("device_type", "")
        device_match = any(kw in device_type for kw in device_kw)

        original_score = item.get("score", 0)
        if original_score <= 0:
            continue

        if not device_match:
            # 设备类型不匹配 → 故障命中再多也不可信
            adjusted = original_score * 0.2
        else:
            # 设备类型匹配 → 按故障关键词命中率定分
            if fault_hit_count == 0 or fault_ratio < 0.3:
                adjusted = original_score * 0.15
            else:
                adjusted = original_score * (1 + fault_weight * fault_ratio)
        adjusted = min(adjusted, 1.0)

        item["score"] = round(adjusted, 4)
        item["fault_hits"] = fault_hit_count

    # 按调整后分数重排
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results


# ==================== RRF 融合 ====================

# 已告警过 id 不一致的检索方法（防止重复刷日志）
_RRF_ALERTED_METHODS: set = set()


def rrf_merge(
    result_sets: List[List[Dict]],
    k: int = 60,
    top_n: int = 10
) -> List[Dict]:
    """
    Reciprocal Rank Fusion - 融合多个检索结果集

    去重键说明（重要）：
    - 优先使用 knowledge_id（知识库主键，跨检索路稳定）；
    - 向量路的 id 是 Milvus point_id（uuid 字符串），BM25 路的 id 是数据库 id（整数），
      若用 id 做合并键，同一知识会因两路 id 不同被当成两条，导致双路命中的
      RRF 分数不合并（该知识本应得到 1/(k+rank1)+1/(k+rank2)）。
    - 因此统一以 knowledge_id 为合并键；若发现某路结果 id 与 knowledge_id 不一致，
      会打一条 WARNING 告警（每路仅一次），提示后续新增检索路时必须携带 knowledge_id。

    Args:
        result_sets: 多个检索结果列表
        k: RRF 平滑参数 (默认 60)
        top_n: 返回结果数

    Returns:
        融合排序后的结果列表，score 字段为向量余弦相似度
    """
    scores = {}

    for result_set in result_sets:
        for rank, item in enumerate(result_set, start=1):
            # 统一去重键：优先稳定的 knowledge_id，兜底用 id
            raw_id = item.get("id")
            kid = item.get("knowledge_id")
            item_id = kid or raw_id
            if item_id is None:
                continue

            # 防范措施①：一致性告警——同一条结果 id 与 knowledge_id 并存且不同，
            # 说明该检索路携带了不稳定的 id（如 Milvus point_id），提示必须提供 knowledge_id
            method = item.get("method", "unknown")
            if raw_id is not None and kid is not None and str(raw_id) != str(kid):
                if method not in _RRF_ALERTED_METHODS:
                    _RRF_ALERTED_METHODS.add(method)
                    logger.warning(
                        f"[RRF] 检索路 '{method}' 返回的结果 id({raw_id}) 与 "
                        f"knowledge_id({kid}) 不一致，去重已统一使用 knowledge_id；"
                        f"后续新增检索路时必须保证带 knowledge_id 字段，否则同一知识无法合并双路命中分"
                    )

            rrf_score = 1.0 / (k + rank)
            if item_id not in scores:
                scores[item_id] = {"rrf": 0.0, "vector_score": 0.0, "item": item}
            scores[item_id]["rrf"] += rrf_score
            # 只记录向量检索的余弦相似度作为显示分数
            if item.get("method") == "vector_search":
                item_sim = item.get("score", 0)
                if item_sim > scores[item_id]["vector_score"]:
                    scores[item_id]["vector_score"] = item_sim
            # 保留最高单路得分的 item 详情
            item_score = item.get("score", 0)
            if item_score > scores[item_id]["item"].get("score", 0):
                scores[item_id]["item"] = item

    # 按 RRF 得分降序排列
    merged = sorted(scores.values(), key=lambda x: x["rrf"], reverse=True)
    result = []
    for entry in merged[:top_n]:
        item = entry["item"].copy()
        item["rrf_score"] = round(entry["rrf"], 4)
        # 仅使用向量相似度作为展示得分，BM25 独中的条目得分为 0
        # （BM25 关键词匹配无法衡量语义相关性，显示 0% 避免误导）
        display_score = entry["vector_score"]
        item["score"] = round(display_score, 4)
        item["rrf_only"] = display_score <= 0  # 标记：仅 RRF 排序带来，无语义匹配
        result.append(item)

    # 防范措施②：防御性去重——兜底确保返回结果不存在重复 knowledge_id。
    # 正常情况下已按 knowledge_id 合并不会重复；此处防止未来新增检索路时再次引入
    # 不稳定的 id 导致重复条目漏到下游
    seen: set = set()
    unique: List[Dict] = []
    for item in result:
        key = item.get("knowledge_id") or item.get("id")
        if key is None or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


# ==================== 工具实现 ====================

class RetrievalTools:
    """检索助手 Agent 的工具集"""

    def __init__(self, db_session_factory, vector_store, embedding_fn):
        self.db_factory = db_session_factory
        self.vector_store = vector_store
        self.encode = embedding_fn
        # 初始化查询关键词提取器（白名单 + LLM 兜底）
        from app.agents.query_extractor import QueryKeywordExtractor
        self.query_extractor = QueryKeywordExtractor(db_session_factory)

    # ---------- Tool 1: 向量语义检索 ----------

    def vector_search(
        self,
        query: str,
        top_k: int = 10,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        score_threshold: float = 0.3
    ) -> ToolResult:
        """
        向量语义检索 - 基于 embedding 相似度从 Milvus 检索相关知识

        Args:
            query: 自然语言查询文本
            top_k: 返回结果数
            device_type: 可选 - 按设备类型过滤
            fault_code: 可选 - 按故障码过滤
            score_threshold: 相似度阈值
        """
        try:
            # ===== 关键优化：用白名单+LLM提取技术关键词，避免语义向量被干扰词带偏 =====
            cleaned_query = self.query_extractor.extract(query) or query
            query_vector = self.encode(cleaned_query)
            results = self.vector_store.search(
                query_vector=query_vector,
                limit=top_k,
                device_type=device_type,
                fault_code=fault_code,
                score_threshold=score_threshold,
            )
            for r in results:
                r["method"] = "vector_search"
            return ToolResult(
                success=True,
                data=results,
                metadata={"method": "vector_search", "count": len(results)},
            )
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return ToolResult(success=False, data=[], error=str(e))

    # ---------- Tool 2: BM25 关键词检索 ----------

    def bm25_search(
        self,
        query: str,
        top_k: int = 10,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
    ) -> ToolResult:
        """
        BM25 关键词检索 - 基于 PostgreSQL 全文检索的精确关键词匹配

        Args:
            query: 关键词查询文本（支持 AND/OR 逻辑）
            top_k: 返回结果数
            device_type: 可选 - 设备类型过滤
            fault_code: 可选 - 故障码过滤
        """
        try:
            from sqlalchemy import text
            db = self.db_factory()
            try:
                import re
                # ===== 关键优化：用白名单+LLM提取技术关键词 =====
                raw = self.query_extractor.extract(query.strip()) or query.strip()
                if not raw:
                    return ToolResult(success=True, data=[], metadata={"method": "bm25_search", "count": 0})

                # 中文分词：拆分为 2-gram 重叠片段 + 英文/数字按空格分词
                tokens = set()
                chinese_spans = re.findall(r'[\u4e00-\u9fff]+', raw)
                for span in chinese_spans:
                    for i in range(len(span)):
                        for n in [2, 3]:
                            if i + n <= len(span):
                                tokens.add(span[i:i+n])
                    tokens.add(span)
                # 英文/数字部分
                non_chinese = re.sub(r'[\u4e00-\u9fff]+', ' ', raw)
                for w in non_chinese.split():
                    if len(w) >= 2:
                        tokens.add(w)

                words = list(tokens)
                if not words:
                    return ToolResult(success=True, data=[], metadata={"method": "bm25_search", "count": 0})

                # 分类关键词：设备类型 vs 故障原因
                device_kw, fault_kw = _classify_keywords(set(words))

                # 构建 ILIKE 条件：标题或内容包含任一关键词（OR 逻辑）
                like_clauses = []
                params = {"limit": top_k, "device_filter": device_type or None, "fault_filter": f"%{fault_code}%" if fault_code else None}
                for i, w in enumerate(words):
                    like_clauses.append(f"(title ILIKE :kw_{i} OR content ILIKE :kw_{i})")
                    params[f"kw_{i}"] = f"%{w}%"

                # 加权评分：故障原因关键词权重高，设备类型关键词权重低
                rank_parts = []
                for i, w in enumerate(words):
                    if w in fault_kw:
                        title_w = FAULT_CAUSE_WEIGHT
                        content_w = FAULT_CONTENT_WEIGHT
                    else:
                        title_w = DEVICE_TYPE_WEIGHT
                        content_w = DEVICE_CONTENT_WEIGHT
                    rank_parts.append(
                        f"(CASE WHEN title ILIKE :kw_{i} THEN {title_w} ELSE 0 END"
                        f" + CASE WHEN content ILIKE :kw_{i} THEN {content_w} ELSE 0 END)"
                    )
                rank_expr = " + ".join(rank_parts)
                where_extra = " OR ".join(like_clauses)

                sql = text(f"""
                    SELECT
                        id, title, content, device_type, fault_code, fault_tags,
                        ({rank_expr}) AS score
                    FROM knowledge_items
                    WHERE 1=1
                        AND ({where_extra})
                        AND (:device_filter IS NULL OR device_type = :device_filter)
                        AND (:fault_filter IS NULL OR fault_code LIKE :fault_filter)
                    ORDER BY score DESC, id DESC
                    LIMIT :limit
                """)
                rows = db.execute(sql, params).fetchall()

                results = []
                for row in rows:
                    results.append({
                        "id": row.id,
                        "knowledge_id": row.id,
                        "title": row.title,
                        "content": row.content[:500] if row.content else "",
                        "device_type": row.device_type,
                        "fault_code": row.fault_code,
                        "fault_tags": row.fault_tags or [],
                        "score": round(float(row.score), 4),
                        "method": "bm25_search",
                    })

                return ToolResult(
                    success=True,
                    data=results,
                    metadata={"method": "bm25_search", "count": len(results)},
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"BM25 检索失败: {e}")
            # 降级：用 LIKE 进行简单关键词匹配
            try:
                db = self.db_factory()
                try:
                    from app.models.knowledge import KnowledgeItem, KnowledgeStatus
                    query_filter = db.query(KnowledgeItem).filter(
                        KnowledgeItem.status == KnowledgeStatus.PUBLISHED
                    )
                    for word in query.strip().split():
                        query_filter = query_filter.filter(
                            KnowledgeItem.title.ilike(f"%{word}%")
                            | KnowledgeItem.content.ilike(f"%{word}%")
                        )
                    if device_type:
                        query_filter = query_filter.filter(KnowledgeItem.device_type == device_type)
                    if fault_code:
                        query_filter = query_filter.filter(KnowledgeItem.fault_code.like(f"%{fault_code}%"))
                    items = query_filter.limit(top_k).all()
                    results = []
                    for item in items:
                        results.append({
                            "id": item.id,
                            "knowledge_id": item.id,
                            "title": item.title,
                            "content": item.content[:500] if item.content else "",
                            "device_type": item.device_type,
                            "fault_code": item.fault_code,
                            "fault_tags": item.fault_tags or [],
                            "score": 1.0,  # LIKE 匹配无精确排名
                            "method": "bm25_search",
                        })
                    return ToolResult(
                        success=True,
                        data=results,
                        metadata={"method": "bm25_fallback_like", "count": len(results)},
                    )
                finally:
                    db.close()
            except Exception as e2:
                logger.error(f"BM25 降级检索也失败: {e2}")
                return ToolResult(success=False, data=[], error=str(e2))

    # ---------- Tool 3: 条件精确查询 ----------

    def conditional_query(
        self,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        tags: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        top_k: int = 20,
    ) -> ToolResult:
        """
        条件精确查询 - 按结构化字段精确匹配知识条目

        Args:
            device_type: 设备类型
            fault_code: 故障码
            tags: 故障标签列表
            keyword: 标题/内容模糊匹配
            top_k: 返回结果数
        """
        try:
            db = self.db_factory()
            try:
                from app.models.knowledge import KnowledgeItem, KnowledgeStatus
                query_obj = db.query(KnowledgeItem).filter(
                    KnowledgeItem.status == KnowledgeStatus.PUBLISHED
                )
                if device_type:
                    query_obj = query_obj.filter(KnowledgeItem.device_type == device_type)
                if fault_code:
                    query_obj = query_obj.filter(KnowledgeItem.fault_code.like(f"%{fault_code}%"))
                if keyword:
                    query_obj = query_obj.filter(
                        KnowledgeItem.title.ilike(f"%{keyword}%")
                        | KnowledgeItem.content.ilike(f"%{keyword}%")
                    )

                items = query_obj.order_by(KnowledgeItem.id.desc()).limit(top_k * 2 if tags else top_k).all()

                # 标签过滤在 Python 层面做
                if tags:
                    filtered = []
                    for item in items:
                        item_tags = item.fault_tags or []
                        if isinstance(item_tags, list) and any(t in item_tags for t in tags):
                            filtered.append(item)
                    items = filtered[:top_k]
                results = []
                for item in items:
                    results.append({
                        "id": item.id,
                        "knowledge_id": item.id,
                        "title": item.title,
                        "content": item.content[:500] if item.content else "",
                        "device_type": item.device_type,
                        "fault_code": item.fault_code,
                        "fault_tags": item.fault_tags or [],
                        "score": 1.0,
                    })
                return ToolResult(
                    success=True,
                    data=results,
                    metadata={"method": "conditional_query", "count": len(results)},
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"条件查询失败: {e}")
            return ToolResult(success=False, data=[], error=str(e))

    # ---------- Tool 4: 查询改写 ----------

    def rewrite_query(
        self,
        original_query: str,
        context: str = "设备维修知识库",
        strategy: str = "expand_synonyms"
    ) -> ToolResult:
        """
        查询改写 - 用 LLM 优化模糊查询，生成更专业的检索关键词

        Args:
            original_query: 原始用户查询
            context: 上下文领域描述
            strategy: 改写策略 (expand_synonyms | technical_terms | generalize)
        """
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, SystemMessage
            from app.core.config import settings

            llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.3,
                streaming=False,
            )

            system_prompt = f"""你是一个{context}的查询优化助手。
用户会提出关于设备故障和维修的问题，你需要将口语化、模糊的查询改写为更专业、精确的检索关键词。

改写规则：
1. 保留用户原始意图和核心概念
2. 将口语化表述转为专业术语（如"声音不对"→"异常噪音"）
3. 补充同义词和相关词（如"电机"→"电动机/马达"）
4. 拆解复杂查询为多个简洁的检索短语
5. 生成 1-3 个改写版本

请以 JSON 数组格式输出改写后的查询，示例：
["改写查询1", "改写查询2"]"""

            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"请改写以下查询：{original_query}\n\n请以 JSON 数组格式返回改写结果。")
            ])

            # 解析 LLM 返回的 JSON
            content = response.content.strip()
            # 清理 markdown 代码块标记
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
            rewritten = json.loads(content)

            if not isinstance(rewritten, list):
                rewritten = [str(rewritten)]

            return ToolResult(
                success=True,
                data=rewritten,
                metadata={
                    "original": original_query,
                    "strategy": strategy,
                    "rewritten_count": len(rewritten),
                },
            )
        except Exception as e:
            logger.error(f"查询改写失败: {e}")
            # 降级：简单拆分和补充同义词
            fallback = [original_query]
            return ToolResult(
                success=True,
                data=fallback,
                metadata={"original": original_query, "method": "fallback", "error": str(e)},
            )

    # ---------- Tool 5: 知识图关联查询 ----------

    def graph_query(
        self,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        exclude_ids: Optional[List[int]] = None,
        top_k: int = 10,
    ) -> ToolResult:
        """
        知识图关联查询 - 查询与指定设备/故障相关的知识条目

        Args:
            device_type: 设备类型 (以此为起点展开关联)
            fault_code: 故障码
            exclude_ids: 排除的知识条目 ID 列表
            top_k: 返回结果数
        """
        try:
            db = self.db_factory()
            try:
                from app.models.knowledge import KnowledgeItem, KnowledgeStatus
                query_obj = db.query(KnowledgeItem).filter(
                    KnowledgeItem.status == KnowledgeStatus.PUBLISHED
                )
                if device_type:
                    query_obj = query_obj.filter(KnowledgeItem.device_type == device_type)
                if fault_code:
                    query_obj = query_obj.filter(KnowledgeItem.fault_code.like(f"%{fault_code}%"))
                if exclude_ids:
                    query_obj = query_obj.filter(~KnowledgeItem.id.in_(exclude_ids))

                items = query_obj.order_by(KnowledgeItem.id.desc()).limit(top_k).all()
                results = []
                for item in items:
                    results.append({
                        "id": item.id,
                        "knowledge_id": item.id,
                        "title": item.title,
                        "content": item.content[:500] if item.content else "",
                        "device_type": item.device_type,
                        "fault_code": item.fault_code,
                        "fault_tags": item.fault_tags or [],
                        "score": 1.0,
                    })
                return ToolResult(
                    success=True,
                    data=results,
                    metadata={
                        "method": "graph_query",
                        "device_type": device_type,
                        "fault_code": fault_code,
                        "count": len(results),
                    },
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"图谱查询失败: {e}")
            return ToolResult(success=False, data=[], error=str(e))
