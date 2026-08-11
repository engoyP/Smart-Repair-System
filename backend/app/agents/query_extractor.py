"""查询关键词提取器 — 白名单优先 + LLM 兜底

策略：
  1. 白名单匹配（0 成本、0 延迟）：
     - 从 DB 加载所有 device_type 和 fault_tags → 构建白名单
     - 叠加内置的设备类型词、故障信号词
     - 从用户提问中抽取命中白名单的词 + 英文/数字/故障码
     - 命中 >=1 个 → 直接返回
  2. LLM 兜底（白名单 0 命中时）：
     - 调 DeepSeek 提取技术关键词
     - 结果缓存（相同提问不重复调用）
"""
import re
import time
from typing import Optional, Set, List
from loguru import logger


class QueryKeywordExtractor:
    """查询关键词提取器：白名单优先，LLM 兜底"""

    # 内置设备类型词（编译期已知）
    _BUILTIN_DEVICE_TERMS: Set[str] = {
        "注塑机", "数控机床", "CNC", "液压系统", "传送带", "空压机", "变压器",
        "电机", "锅炉", "制冷系统", "机器人", "输送设备", "PLC", "PLC系统",
        "机床", "设备", "机器", "机器设备", "加工中心",
    }

    # 内置故障信号词（编译期已知）
    _BUILTIN_FAULT_SIGNALS: Set[str] = {
        "故障", "异常", "报警", "失效", "损坏", "磨损", "泄漏", "堵塞", "卡死",
        "过热", "过载", "短路", "断路", "烧毁", "断裂", "变形", "腐蚀", "老化",
        "偏高", "偏低", "不稳定", "波动", "不足", "过大", "过高", "过低",
        "异响", "振动", "噪音", "漏油", "停机", "跳闸", "不转", "不动作",
        "失灵", "失控", "无法启动", "无法加载", "无法卸载",
        "打滑", "跑偏", "爬行", "抖动", "冲击",
        "温度", "压力", "流量", "电压", "电流", "绝缘", "润滑", "冷却", "加热",
        "指示灯", "不亮", "不工作", "死机", "黑屏", "无输出", "无响应",
        "报错", "卡住", "闪屏", "乱码", "不识别", "不启动", "断开",
        "无法连接", "无法读取", "不显示", "不运行", "没反应",
        "不通讯", "通讯中断", "信号弱", "丢包", "延迟高",
        "RAM错误", "程序丢失", "电池电压", "电源波动",
    }

    def __init__(self, db_session_factory):
        self._db_factory = db_session_factory
        self._whitelist: Optional[Set[str]] = None
        self._whitelist_loaded_at: float = 0
        self._whitelist_ttl: float = 300  # 5 分钟刷新一次白名单
        self._llm_cache: dict[str, tuple[str, float]] = {}  # query -> (result, timestamp)
        self._llm_cache_ttl: float = 600  # 10 分钟缓存
        self._llm = None

    @property
    def llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            from app.core.config import settings
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.1,
                streaming=False,
                timeout=15,            # 关键词提取兜底调用，超时直接返回原始查询
                max_retries=1,
            )
        return self._llm

    def _load_whitelist(self) -> Set[str]:
        """从数据库加载设备类型和故障标签，合并内置词库"""
        if self._whitelist is not None and (time.time() - self._whitelist_loaded_at) < self._whitelist_ttl:
            return self._whitelist

        wl = set(self._BUILTIN_DEVICE_TERMS) | set(self._BUILTIN_FAULT_SIGNALS)

        try:
            db = self._db_factory()
            try:
                from app.models.knowledge import KnowledgeItem, KnowledgeStatus
                # 加载所有已发布知识的 device_type
                device_types = db.query(KnowledgeItem.device_type).filter(
                    KnowledgeItem.device_type.isnot(None),
                    KnowledgeItem.status == KnowledgeStatus.PUBLISHED
                ).distinct().all()
                for row in device_types:
                    if row[0]:
                        wl.add(row[0].strip())

                # 加载所有 fault_tags（JSONB 数组）
                fault_tags_rows = db.query(KnowledgeItem.fault_tags).filter(
                    KnowledgeItem.fault_tags.isnot(None),
                    KnowledgeItem.status == KnowledgeStatus.PUBLISHED
                ).all()
                for row in fault_tags_rows:
                    tags = row[0]
                    if isinstance(tags, list):
                        for t in tags:
                            if t and isinstance(t, str):
                                wl.add(t.strip())
                logger.info(f"[QueryExtractor] 白名单加载完成: {len(wl)} 个词")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[QueryExtractor] 白名单加载失败，使用内置词库: {e}")

        self._whitelist = wl
        self._whitelist_loaded_at = time.time()
        return wl

    def _extract_by_whitelist(self, query: str) -> List[str]:
        """白名单提取：从提问中匹配已知设备/故障词 + 英文/数字/故障码"""
        if not query:
            return []

        wl = self._load_whitelist()
        found: List[str] = []

        # 1. 匹配白名单中的词（按长度降序，优先长词匹配，避免"PLC"吃掉"PLC系统"）
        sorted_wl = sorted(wl, key=len, reverse=True)
        query_remaining = query
        for term in sorted_wl:
            if term in query_remaining:
                found.append(term)
                # 不从 query_remaining 中删除，因为同一词可能多次出现（保留即可）
                # 但为了避免短词在长词内部误匹配，标记已匹配区域
                query_remaining = query_remaining.replace(term, " " * len(term), 1)

        # 2. 提取英文/数字 token（PLC、RAM、6101、SMS_337505573 等）
        for m in re.finditer(r'[A-Za-z][A-Za-z0-9_\-]{1,}', query):
            tok = m.group(0)
            if tok not in found and len(tok) >= 2:
                found.append(tok)

        # 3. 提取纯数字（可能是故障码）
        for m in re.finditer(r'\d{3,}', query):
            tok = m.group(0)
            if tok not in found:
                found.append(tok)

        return found

    def _extract_by_llm(self, query: str) -> str:
        """LLM 兜底：调 DeepSeek 提取技术关键词"""
        # 检查缓存
        cached = self._llm_cache.get(query)
        if cached and (time.time() - cached[1]) < self._llm_cache_ttl:
            logger.info(f"[QueryExtractor] LLM 缓存命中: {query} → {cached[0]}")
            return cached[0]

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system_prompt = """你是一个设备维修知识库的关键词提取助手。
用户会输入一段关于设备故障的提问，你需要从中提取出纯粹的技术关键词：设备类型、故障现象、故障代码、部件名称。

规则：
1. 只返回技术关键词，去掉所有疑问词、口语修饰、请求动词
2. 用空格分隔多个关键词
3. 不要返回标点符号
4. 不要解释，直接输出关键词

示例：
- "PLC报RAM错误代码怎么处理？" → PLC RAM 错误代码
- "注塑机的温度偏高可能是哪方面的问题" → 注塑机 温度偏高
- "帮我看看传送带的电机不转了怎么回事" → 传送带 电机 不转"""

            response = self.llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"提取关键词：{query}"),
            ])
            result = response.content.strip()
            # 清理可能的 markdown 标记
            if result.startswith("```"):
                result = result.split("\n", 1)[-1]
                if result.endswith("```"):
                    result = result[:-3]
                result = result.strip()

            logger.info(f"[QueryExtractor] LLM 提取: {query} → {result}")
            self._llm_cache[query] = (result, time.time())
            return result
        except Exception as e:
            logger.error(f"[QueryExtractor] LLM 提取失败: {e}")
            # 降级：返回原始查询
            return query

    def extract(self, query: str, use_llm_fallback: bool = True) -> str:
        """
        主入口：提取技术关键词

        Args:
            query: 用户原始提问
            use_llm_fallback: 白名单 0 命中时是否调 LLM 兜底

        Returns:
            空格拼接的技术关键词字符串
        """
        if not query or not query.strip():
            return ""

        # Step 1: 白名单提取
        keywords = self._extract_by_whitelist(query)

        if keywords:
            result = " ".join(keywords)
            logger.info(f"[QueryExtractor] 白名单命中: {query} → {result}")
            return result

        # Step 2: 白名单 0 命中 → LLM 兜底
        if use_llm_fallback:
            return self._extract_by_llm(query)

        # 不用 LLM 时，降级为原始查询
        logger.info(f"[QueryExtractor] 白名单 0 命中且不调 LLM，返回原始: {query}")
        return query
