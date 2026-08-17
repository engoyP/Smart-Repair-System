"""KnowledgeExtractorAgent - 从已审核工单中自动提取知识条目

功能：
- 从工单的标准化字段、根因、方案中提炼知识条目
- 生成结构化内容（故障描述 → 排查步骤 → 处理方法 → 预防措施）
- 提取标签和设备类型分类

集成 LangFuse 追踪。
"""
import json
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from loguru import logger
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import settings
from app.core.langfuse_tracer import tracer


@dataclass
class ExtractedKnowledge:
    """从工单中提取的知识条目"""
    title: str = ""
    content: str = ""
    fault_code: str = ""
    device_type: str = ""
    fault_tags: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)  # 用于去重检测的关键词
    raw_response: str = ""


class KnowledgeExtractorAgent:
    """知识提取智能体 - 将工单转化为结构化知识"""

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.2,
                streaming=False,
            )
        return self._llm

    def extract(self, work_order_data: Dict) -> ExtractedKnowledge:
        """
        从工单数据中提取知识条目

        Args:
            work_order_data: 工单数据，包含 fault_description, fault_code,
                             fault_phenomenon, root_cause, solution_steps,
                             device_type (from analysis), tags, etc.

        Returns:
            ExtractedKnowledge 结构化知识
        """
        fault_description = work_order_data.get("fault_description", "")
        fault_code = work_order_data.get("fault_code", "")
        fault_phenomenon = work_order_data.get("fault_phenomenon", "")
        root_cause = work_order_data.get("root_cause", "")
        solution_steps = work_order_data.get("solution_steps", "")
        device_type = work_order_data.get("device_type", "")
        tags = work_order_data.get("tags", [])
        log_text = work_order_data.get("log_text", "")

        if not fault_description:
            return ExtractedKnowledge()

        result = self._invoke_extraction(
            fault_description=fault_description,
            fault_code=fault_code,
            fault_phenomenon=fault_phenomenon,
            root_cause=root_cause,
            solution_steps=solution_steps,
            device_type=device_type,
            tags=tags,
            log_text=log_text,
        )

        logger.info(f"[KnowledgeExtractor] 提取完成: {result.title[:50] if result.title else '空'}...")
        return result

    def _invoke_extraction(
        self,
        fault_description: str,
        fault_code: str,
        fault_phenomenon: str,
        root_cause: str,
        solution_steps: str,
        device_type: str,
        tags: List[str],
        log_text: str = "",
    ) -> ExtractedKnowledge:
        """调用 LLM 提取知识（带 LangFuse 追踪）"""

        system_prompt = """你是一个设备维修知识管理专家。你的任务是从已完成的维修工单中提取有价值的知识条目。

## 知识条目要求
- **title**: 简洁准确的知识标题（15-30字），格式建议 "【设备类型】故障现象 - 处理方法"
- **content**: 结构化知识内容，采用以下格式：
  ```
  ## 故障现象
  （描述典型表现）

  ## 原因分析
  （根因分析）

  ## 排查步骤
  1. ...
  2. ...

  ## 处理方法
  1. ...
  2. ...

  ## 预防措施
  - ...
  ```

- **fault_code**: 工单中的故障码，如无则为空；工单附带"设备日志原文"时，从日志中提取报警码（如 SV0436）并入 fault_code
- **device_type**: 设备类型
- **fault_tags**: 3-5个关键词标签（用于分类和检索），工单附带日志原文时可从中提取报警码/信号词作为标签
- **keywords**: 3-5个用于去重比对的关键词/短语（提取最具区分度的关键词）

## 设备日志原文处理规则（重要）
工单可能附带"设备日志原文"（维修工粘贴的设备屏幕/日志文本，含时间戳、十六进制行等噪音）：
1. 日志原文**仅用于提取错误码/报警码与信号词**，写入 fault_code / fault_tags；
2. **不得把日志原文整段粘贴进 content**——日志噪音会污染知识检索质量；
3. content 中可以有一句摘要式引用（如"设备日志显示 SV0436 过电流报警"），但不得含时间戳/十六进制行；
4. 日志中提取不到有效信息时忽略该字段。

## 返回格式（严格 JSON）：
{
  "title": "...",
  "content": "...",
  "fault_code": "...",
  "device_type": "...",
  "fault_tags": ["标签1", "标签2"],
  "keywords": ["关键词1", "关键词2", "关键词3"]
}"""

        user_message = f"""请从以下维修工单中提取知识条目：

## 工单信息
- 设备类型：{device_type or '未指定'}
- 故障码：{fault_code or '未填写'}
- 故障描述：{fault_description}
- 故障现象：{fault_phenomenon or '未填写'}
- 根本原因：{root_cause or '未填写'}
- 解决方案：{solution_steps or '未填写'}
- 设备日志原文：{log_text[:500] if log_text else '未填写'}
- 已有标签：{', '.join(tags) if tags else '无'}

请提取知识条目，返回 JSON。"""

        try:
            with tracer.trace("knowledge_extract", metadata={
                "fault_code": fault_code,
                "device_type": device_type,
            }) as trace_obj:

                start = time.time()
                response = self.llm.invoke([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ])
                elapsed = time.time() - start

                with trace_obj.generation(
                    "knowledge_llm_call",
                    model=settings.DEEPSEEK_MODEL,
                    prompt=user_message,
                    response=response.content,
                    metadata={"elapsed_s": round(elapsed, 2)},
                ):
                    pass

                content = response.content.strip()
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:])
                    if content.endswith("```"):
                        content = content[:-3]
                content = content.strip()

                data = json.loads(content)

                return ExtractedKnowledge(
                    title=data.get("title", ""),
                    content=data.get("content", ""),
                    fault_code=data.get("fault_code", fault_code),
                    device_type=data.get("device_type", device_type),
                    fault_tags=data.get("fault_tags", []),
                    keywords=data.get("keywords", []),
                    raw_response=json.dumps(data, ensure_ascii=False),
                )

        except Exception as e:
            logger.error(f"[KnowledgeExtractor] 提取失败: {e}")
            return ExtractedKnowledge()


# 全局单例
knowledge_extractor = KnowledgeExtractorAgent()
