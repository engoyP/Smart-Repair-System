"""DedupAgent - 知识条目去重判定 Agent

用 LLM 对比两个知识条目的故障原因和处理方案，
判断是否为真正重复（同原因+同方案）还是相似案例（不同原因/方案）。

维修场景下，同设备同故障可能有不同原因和方案，不能仅凭标题相似度判定重复。
"""
import json
from typing import Optional, Dict, List
from dataclasses import dataclass
from loguru import logger

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import settings
from app.core.langfuse_tracer import tracer


@dataclass
class DedupDecision:
    """去重判定结果"""
    is_duplicate: bool = False
    reason: str = ""
    confidence: float = 0.0
    match_score: float = 0.0  # 向量相似度
    title_similarity: float = 0.0
    root_cause_diff: str = ""  # 原因差异描述
    solution_diff: str = ""    # 方案差异描述


class DedupAgent:
    """知识去重 Agent - 用 LLM 判断两个维修知识条目是否为真正重复"""

    SYSTEM_PROMPT = """你是一个设备维修知识库的去重审查专家。你的任务是判断两个维修知识条目是否属于"真正重复"。

## 判定标准
**真正重复**：两篇知识在描述的核心故障原因和处理方法上实质相同（即使措辞、故障码编号、设备类型名称表述略有差异）。
**相似案例**（不算重复）：两篇知识的故障原因 OR 处理方法有本质不同。

## 判定规则（严格遵守）
1. **核心内容优先**：忽略标题差异、故障码数字编号差异、设备类型细微表述差异（如"PLC电源模块" vs "PLC系统"），重点看内容中的**故障原因**和**处理方案**是否实质相同。
2. **原因和方案都相同才算重复**：只有故障原因和处理方案都基本一致（允许措辞差异），才判定为真正重复。
3. **仅标题相似不算**：如果只有标题相似但原因或方案不同，不算重复。
4. **措辞差异忽略**：如"PLC电源模块保险丝熔断" vs "电源模块保险丝熔断"视为相同原因；"更换电源模块保险丝" vs "更换电源模块保险丝处理"视为相同方案。
5. **故障码差异忽略**：故障码（如6401 vs PLC_PWR_001）是人工编号，不作为重复判定依据。
6. **设备类型轻微差异忽略**："PLC"、"PLC系统"、"PLC电源模块"视为同一设备类型。

## 输出格式
请以 JSON 格式输出判定结果：
```json
{
  "is_duplicate": true/false,
  "reason": "判定理由（一句话）",
  "confidence": 0.0-1.0,
  "root_cause_diff": "故障原因差异描述（如实质相同则写'实质相同'）",
  "solution_diff": "处理方案差异描述（如实质相同则写'实质相同'）"
}
```"""

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
                timeout=30,            # 去重判定超时 30s，超时走保守策略（不判重复）
                max_retries=1,
            )
        return self._llm

    def check(self, new_item: dict, existing_item: dict, title_similarity: float = 0.0) -> DedupDecision:
        """
        判断新知识条目是否与已有条目重复

        Args:
            new_item: 新知识条目 {title, content, device_type, fault_code}
            existing_item: 已有知识条目 {title, content, device_type, fault_code}
            title_similarity: 向量检索的标题相似度

        Returns:
            DedupDecision 判定结果
        """
        try:
            with tracer.trace("dedup_check", metadata={
                "new_title": new_item.get("title", ""),
                "existing_title": existing_item.get("title", ""),
                "title_similarity": title_similarity,
            }) as trace_ctx:
                user_prompt = f"""请判断以下两个维修知识条目是否为真正重复：

## 新知识条目
- 标题：{new_item.get('title', '')}
- 设备类型：{new_item.get('device_type', '')}
- 故障码：{new_item.get('fault_code', '')}
- 内容：
{new_item.get('content', '')[:2000]}

## 已有知识条目
- 标题：{existing_item.get('title', '')}
- 设备类型：{existing_item.get('device_type', '')}
- 故障码：{existing_item.get('fault_code', '')}
- 内容：
{existing_item.get('content', '')[:2000]}

## 向量相似度
标题向量相似度：{title_similarity:.2%}

请判定是否为真正重复，以 JSON 格式输出。"""

                response = self.llm.invoke([
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ])

                result = self._parse_response(response.content, title_similarity)
                trace_ctx.score("dedup_confidence", result.confidence)
                trace_ctx.score("is_duplicate", 1.0 if result.is_duplicate else 0.0)
                return result

        except Exception as e:
            logger.error(f"[DedupAgent] 判定失败: {e}")
            # 降级：保守策略，不确定时不判定为重复
            return DedupDecision(
                is_duplicate=False,
                reason=f"判定异常: {e}",
                confidence=0.0,
                match_score=title_similarity,
                title_similarity=title_similarity,
            )

    def _parse_response(self, content: str, title_similarity: float) -> DedupDecision:
        """解析 LLM 返回的 JSON"""
        try:
            # 清理 markdown 代码块
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)

            data = json.loads(text)
            return DedupDecision(
                is_duplicate=data.get("is_duplicate", False),
                reason=data.get("reason", ""),
                confidence=data.get("confidence", 0.0),
                match_score=title_similarity,
                title_similarity=title_similarity,
                root_cause_diff=data.get("root_cause_diff", ""),
                solution_diff=data.get("solution_diff", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[DedupAgent] JSON 解析失败: {e}, raw: {content[:200]}")
            # 降级：从文本中尝试提取关键词判断
            text_lower = content.lower()
            if "true" in text_lower and ("是重复" in content or "真正重复" in content or "is_duplicate" in content):
                return DedupDecision(
                    is_duplicate=True,
                    reason=content[:200],
                    confidence=0.5,
                    match_score=title_similarity,
                    title_similarity=title_similarity,
                )
            return DedupDecision(
                is_duplicate=False,
                reason=f"解析失败，保守跳过: {content[:200]}",
                confidence=0.0,
                match_score=title_similarity,
                title_similarity=title_similarity,
            )


dedup_agent = DedupAgent()