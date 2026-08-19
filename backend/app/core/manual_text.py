"""手册条目文本拼装 - 导入脚本 / API / 检索三处共用的纯函数

结构化改造后手册条目的两种文本形态：
1. 嵌入文本（build_manual_embedding_text）：写入 Milvus 的向量编码源
   锚点 = error_code + title + message_text（屏幕原文）+ description + 前 3 情形的信号/原因
2. 内容文本（build_manual_content_text）：给 LLM/前端展示的完整结构化文本
   conditions 非空时按情形分组输出；为空回退旧平铺格式（过渡期兼容）
"""
from typing import Dict, List, Optional

from app.core.config import settings


def normalize_error_code(code: str) -> str:
    """错误码归一化：去首尾空白 + 转大写（与 extract_error_codes 的归一化一致）"""
    return (code or "").strip().upper()


def build_manual_embedding_text(e: Dict) -> str:
    """手册条目向量编码文本（各写入路径统一使用）

    优先覆盖日志原文匹配：error_code 与 message_text 是日志里必然出现的形态；
    前 3 个情形的 signal/cause 让"伴随信号词"也能语义命中。
    """
    parts = [
        str(e.get("error_code") or ""),
        str(e.get("title") or ""),
        str(e.get("message_text") or ""),
        str(e.get("description") or ""),
    ]
    conditions = e.get("conditions") or []
    if isinstance(conditions, list) and conditions:
        for c in conditions[:3]:
            if isinstance(c, dict) and (c.get("signal") or c.get("cause")):
                parts.append(f"{c.get('signal', '')} {c.get('cause', '')}")
    text = " ".join(p for p in parts if p)
    return text[: settings.MAX_MANUAL_VECTOR_TEXT_LEN]


def build_manual_content_text(e: Dict) -> str:
    """手册条目完整内容文本（LLM 提示词与前端展示共用）

    conditions 非空：结构化输出（【情形N】信号/原因/处理 分组，保持对应关系）；
    conditions 为空：回退旧平铺格式（description + 原因 + 处理），过渡期兼容。
    """
    conditions = e.get("conditions") or []
    if isinstance(conditions, list) and conditions:
        lines = []
        if e.get("message_text"):
            lines.append(f"【屏幕原文】{e['message_text']}")
        if e.get("description"):
            lines.append(f"【说明】{e['description']}")
        for i, c in enumerate(conditions, 1):
            if not isinstance(c, dict):
                continue
            seg = [f"【情形{i}】"]
            if c.get("signal"):
                seg.append(f"信号: {c['signal']}")
            if c.get("cause"):
                seg.append(f"原因: {c['cause']}")
            if c.get("steps"):
                seg.append(f"处理: {c['steps']}")
            lines.append(" | ".join(seg))
        related = e.get("related_codes") or []
        if isinstance(related, list) and related:
            lines.append(f"【伴随报警】{', '.join(str(x) for x in related)}")
        return "\n".join(lines)

    # 旧格式回退（conditions 未结构化时的过渡期兼容）
    parts = [str(e.get("description") or "")]
    if e.get("causes"):
        parts.append(f"原因：{e['causes']}")
    if e.get("solutions"):
        parts.append(f"处理：{e['solutions']}")
    return "\n".join(p for p in parts if p)
