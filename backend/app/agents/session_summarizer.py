"""会话摘要 Agent - 用于压缩长对话历史"""
from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import settings


class SessionSummarizer:
    """将会话消息列表压缩为结构化摘要"""

    SYSTEM_PROMPT = """你是一个维修知识系统的会话摘要专家。请将以下维修技术对话压缩为结构化摘要。

要求：
1. 提取这次对话中用户关心的问题和 AI 给出的核心结论
2. 列出提到过的设备类型、故障现象、故障码
3. 保留所有确认过的诊断结论和处理方案
4. 删除冗余的问候语、重复表述
5. 用简洁的中文输出，保留技术细节

输出格式：
---
## 会话摘要
用户核心问题：...
涉及设备/故障：...

### 已确认信息
- ...

### 诊断结论与处理方案
- ...

### 未解决的问题/待办
- ...
---"""

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        if not self._llm:
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.3,
                max_tokens=1024,
            )
        return self._llm

    def summarize(self, messages: List[dict]) -> str:
        """对消息列表生成结构化摘要

        Args:
            messages: [{"role": "user"|"assistant", "content": "..."}, ...]

        Returns:
            str: 结构化摘要文本
        """
        if not messages:
            return "对话为空"

        # 构建对话文本
        dialog = ""
        for i, m in enumerate(messages, 1):
            role = "用户" if m.get("role") == "user" else "AI"
            content = m.get("content", "")
            # 截断过长的单条消息
            if len(content) > 800:
                content = content[:800] + "…(截断)"
            dialog += f"[{i}] {role}：{content}\n\n"

        prompt = f"""以下是维修技术对话记录，请按要求生成结构化摘要：

{dialog}

请输出结构化摘要。"""

        resp = self.llm.invoke([
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        return resp.content.strip()


session_summarizer = SessionSummarizer()
