"""FaultDecomposer - 复合故障问题拆解器

把"同一设备同时出现多个故障现象"的复合提问，拆成多个单故障子查询，
每个子查询保留设备/故障码上下文，供专家模式按故障分组并行检索。

单一故障或无法判断时，直接返回 [原问题]，不产生额外 LLM 调用。
"""
import json
from typing import List, Optional
from loguru import logger

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import settings
from app.core.langfuse_tracer import tracer

# 连接词/分隔符：出现时大概率是复合问题
_CONNECTORS = (
    "还有", "以及", "同时", "加上", "外加", "并且", "而且", "再",
    "又", "、", "，", ",", "和",
)

# 触发拆解的最低不同故障信号词数量（需同时命中连接词）
_TRIGGER_SIGNAL_COUNT = 2

# 拆解上限：避免多故障时检索路数爆炸
_MAX_SUB_QUERIES = 4


class FaultDecomposer:
    """复合故障问题拆解器：规则预检 + LLM 拆解 + 保守兜底"""

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.1,
                streaming=False,
                timeout=15,            # 拆解是轻量调用，15s 足够；超时直接回退为单故障直通
                max_retries=1,
            )
        return self._llm

    def decompose(self, question: str) -> List[str]:
        """拆解复合问题为多个单故障子查询；单一故障返回 [原问题]"""
        q = (question or "").strip()
        if not q:
            return []

        # 规则预检：不像是复合问题则直通（省一次 LLM 调用）
        if not self._looks_compound(q):
            return [q]

        # LLM 拆解
        try:
            with tracer.trace("fault_decompose", metadata={"question": q}) as trace_ctx:
                system_prompt = """你是一个设备维修知识库的故障拆解专家。用户会把"同一设备同时出现的多个故障现象"写在一个提问里，你需要把它们拆成多个单故障检索子查询。

## 拆解规则
1. 只有提问中明确包含 **多个不同故障现象** 时才拆解；单一故障直接返回原问题。
2. 每个子查询必须是**完整的检索语句**：保留设备类型/型号/故障码上下文，只聚焦其中一个故障。
   例如："注塑机温度偏高还有电机异响怎么办" → ["注塑机 温度偏高", "注塑机 电机异响"]
3. 子查询中不要出现"怎么处理/怎么办/为什么"等疑问词和口语修饰词，只保留设备+故障的核心技术词。
4. 最多拆成 4 个子查询；同一故障现象不要重复拆。
5. 无法判断是否多故障时，保守返回原问题。

## 输出格式
严格输出 JSON 数组，例如：["注塑机 温度偏高", "注塑机 电机异响"]"""

                user_prompt = f"请拆解以下维修提问：\n{q}\n\n只输出 JSON 数组。"

                response = self.llm.invoke([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ])
                sub_queries = self._parse(response.content)
                trace_ctx.score("sub_query_count", float(len(sub_queries)))
                if sub_queries:
                    logger.info(f"[FaultDecomposer] {q} → {sub_queries}")
                    return sub_queries
        except Exception as e:
            logger.error(f"[FaultDecomposer] 拆解失败: {e}")

        return [q]

    def _looks_compound(self, question: str) -> bool:
        """规则预检：是否像复合问题（多个故障信号词 + 连接词/分隔符）"""
        from app.agents.tools import _FAULT_CAUSE_SIGNALS

        has_connector = any(c in question for c in _CONNECTORS)
        if not has_connector:
            return False
        signals = {s for s in _FAULT_CAUSE_SIGNALS if s in question}
        return len(signals) >= _TRIGGER_SIGNAL_COUNT

    def _parse(self, content: str) -> List[str]:
        """解析 LLM 返回的 JSON 数组"""
        try:
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            data = json.loads(text)
            if isinstance(data, list):
                items = [str(x).strip() for x in data if str(x).strip()]
                return items[:_MAX_SUB_QUERIES]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[FaultDecomposer] JSON 解析失败: {e}, raw: {content[:200]}")
        return []


fault_decomposer = FaultDecomposer()
