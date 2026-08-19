"""手册原文结构化器 - 粘贴设备手册「错误码表」原文 → DeepSeek 提取结构化条目

用途：手册录入的 LLM 辅助环节。粘贴原文段落，返回结构化 entries
（error_code/title/message_text/description/severity/effect/related_codes/conditions），
由前端回填表单，人工核对后保存。本模块只做结构化、不落库。
"""
import json
from typing import List, Optional

from langchain_openai import ChatOpenAI
from loguru import logger

from app.core.config import settings

_SYSTEM_PROMPT = """你是设备维修手册的结构化录入助手。用户会粘贴设备手册"错误码表"章节的原文（可能是中文或中英混合），
你需要把它拆成结构化 JSON。规则：

1. **一码一条**：原文含多个错误码时输出 entries 数组（一条错误码一个元素）；识别不到错误码则 entries 为空数组。
2. **message_text 逐字照抄**：只填设备屏幕/日志显示的原文（如 "SV0436 AXIS OVERCURRENT ALARM"），不得改写、不得意译；原文没有屏幕原文时留空字符串。
3. **conditions 按情形拆分**：原文中按"情形/条件/如果…则…/故障原因 1)2)3)"自然分段的原因，每段拆成一个 condition：
   - signal：日志或现场**可观察到的信号/触发条件**（如"启动瞬间电流突增报警"、"重载加工中报警"），不要写"可能原因1"这种无信息量的描述；
   - cause：该情形对应的原因；
   - steps：该原因对应的处理/排查步骤，保留测量参数与判断标准原文（如"应>100MΩ"）。
4. **severity 判定**（只输出 EX/OH/INFO）：
   - 原文出现「急停/ESTOP/紧急停止」→ EX
   - 「停机/停止运行/保护性停机」→ OH
   - 「提示/警告/注意/仅显示」或电池、维护类提示 → INFO
   - 判定不了 → OH
5. **effect**（中文，三选一）：EX→"急停"、OH→"停机"、INFO→"仅提示"。
6. **related_codes**：原文中出现的其它错误码/报警号（除本条主错误码外）。
7. **不编造**：原文没有的内容留空；description 保留原文含义但允许整理语句。
8. 输出 JSON 结构：
{"entries": [{"error_code": "SV0436", "title": "伺服放大器过电流报警", "message_text": "", "description": "", "severity": "OH", "effect": "停机", "related_codes": ["SV0401"], "conditions": [{"signal": "", "cause": "", "steps": ""}], "chapter": "", "page": ""}]}
只输出 JSON，不要任何解释文字。"""


def structurize_manual_text(
    text: str,
    manual_name: str = "",
    device_type: str = "",
) -> dict:
    """结构化手册原文，返回 {"entries": [...], "warnings": [...]}

    失败重试一次；两次都失败抛 RuntimeError（由 API 层转 502）。
    """
    if not text or not text.strip():
        raise ValueError("原文为空")

    llm = ChatOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        model=settings.DEEPSEEK_MODEL,
        temperature=0.1,
        streaming=False,
        timeout=60,
        max_retries=1,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    user_prompt = f"【手册名称】{manual_name or '未知'}\n【设备类型】{device_type or '未知'}\n【原文】\n{text[:8000]}"

    last_err: Optional[Exception] = None
    for attempt in range(2):
        try:
            resp = llm.invoke([("system", _SYSTEM_PROMPT), ("user", user_prompt)])
            raw = resp.content.strip()
            # 容错：剥离可能的 ```json 围栏
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            entries = data.get("entries", [])
            if not isinstance(entries, list):
                raise ValueError(f"entries 不是数组: {raw[:200]}")
            # 字段白名单过滤 + 类型规整
            cleaned = [_clean_entry(e) for e in entries if isinstance(e, dict)]
            warnings = data.get("warnings", []) if isinstance(data.get("warnings"), list) else []
            if cleaned and not all(e.get("error_code") for e in cleaned):
                warnings.append("部分条目未识别到错误码")
            return {"entries": cleaned, "warnings": warnings}
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning(f"[ManualStructurizer] 第 {attempt + 1} 次结构化失败: {e}")
    raise RuntimeError(f"手册原文结构化失败: {last_err}")


def _clean_entry(e: dict) -> dict:
    """字段白名单 + 类型规整，防 LLM 输出脏字段"""
    def _str(v, default=""):
        return v if isinstance(v, str) else default

    conditions = e.get("conditions")
    if not isinstance(conditions, list):
        conditions = []
    cleaned_conditions = []
    for c in conditions:
        if not isinstance(c, dict):
            continue
        cleaned_conditions.append({
            "signal": _str(c.get("signal")),
            "cause": _str(c.get("cause")),
            "steps": _str(c.get("steps")),
        })

    related = e.get("related_codes")
    if not isinstance(related, list):
        related = []
    related = [str(x) for x in related if isinstance(x, (str, int))][:20]

    severity = _str(e.get("severity")).upper()
    if severity not in ("EX", "OH", "INFO"):
        severity = "OH"

    return {
        "error_code": _str(e.get("error_code")).strip().upper(),
        "title": _str(e.get("title")),
        "message_text": _str(e.get("message_text")),
        "description": _str(e.get("description")),
        "severity": severity,
        "effect": _str(e.get("effect")),
        "related_codes": related,
        "conditions": cleaned_conditions,
        "chapter": _str(e.get("chapter")),
        "page": _str(e.get("page")),
    }
