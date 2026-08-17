"""钉钉机器人意图路由：LangGraph 图与子图实现

架构：
- 主图（RobotGraph）：router 条件路由 → help / create / todo / inventory / repair 意图节点
- 子图（WoQueryGraph）：工单查询（工单号提取规范化 → 查询并格式化），作为主图节点复用

与旧版 robot_handler._route 的 if-else 相比，意图分发改为图结构，
后续可平滑扩展新节点（如请假、排班查询）而无需改动路由函数。
"""
from __future__ import annotations

import re
from typing import Optional, TypedDict

from loguru import logger
from langgraph.graph import StateGraph, END

from app.mcp import tools

# ============================================================
# 状态定义
# ============================================================
class RobotState(TypedDict, total=False):
    text: str                 # 用户消息原文
    staff_id: str             # 钉钉企业 userId（senderStaffId）
    user_id: Optional[int]    # 系统用户 id（未匹配则为 None）
    user_dt_userid: str       # 系统用户的钉钉绑定 userId
    reply: str                # 最终回复
    wo_no: str                # 工单号（供工单查询子图使用）


class WoSubState(TypedDict, total=False):
    text: str
    wo_no: str
    reply: str


HELP_TEXT = (
    "您好，我是维修助手，可以帮您：\n"
    "1. 输入工单号（如 WO-20260804-001）查询工单状态\n"
    "2. 发送「我的待办」查看名下待处理工单\n"
    "3. 发送设备名称或故障现象（如 注塑机 温度过高），我会结合历史案例一步一步引导您排查故障；排查过程中把检查结果发给我，我会给出下一步操作\n"
    "4. 发送「查备件库存」（如 保险丝还有多少 / 查一下轴承库存），查询备件库存\n"
    "5. 发送「排班」查询今日排班；「明天排班」「我的排班」可查指定日期或本人排班\n"
    "6. 发送「帮助」或「菜单」查看本说明\n"
    "注：工单录入请在系统『维修报表』中新建；部分功能需先登录系统绑定钉钉。"
)

_CREATE_WO_TEXT = "工单录入暂不支持在钉钉操作，请登录系统在『维修报表』中新建工单。"


# ============================================================
# 意图路由（LLM 分类为主，正则快速通道 + 失败兜底）
# ============================================================
_INTENT_HINTS = {
    "help": "查看帮助/功能菜单",
    "create": "录入工单/报修",
    "todo": "查询我的待办/名下工单/任务",
    "workorder": "按工单号查询工单",
    "inventory": "查询备件库存",
    "duty": "查询排班/值班表",
    "repair": "设备故障排查求助/引导维修",
    "none": "与上述功能均无关的内容（闲聊、其他领域的问题等）",
}

_INTENT_PROMPT = """你是维修助手的意图分类器。根据用户消息从以下意图中选择一个，只输出意图名本身，不要解释：
{choices}

规则：
- 只有当消息确实涉及某个功能时才返回对应意图名；
- 如果消息与所有功能都无关（如闲聊、开玩笑、非维修领域问题），必须返回 none；
- 只有消息明确描述了具体设备或故障现象（如 注塑机、电机、PLC、温度过高、不运转、报警 等）时才返回 repair；
- 描述模糊、无法对应到具体设备或故障时返回 none；
- 不要臆测，不确定时返回 none。

用户消息：{text}"""

_llm_classifier = None


def _get_llm_classifier():
    """懒加载 DeepSeek 意图分类器（与 guided_repair_agent 同一套配置）"""
    global _llm_classifier
    if _llm_classifier is None:
        from langchain_openai import ChatOpenAI
        from app.core.config import settings
        _llm_classifier = ChatOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
            temperature=0,
            timeout=15,
        )
    return _llm_classifier


def _classify_intent_llm(text: str) -> str:
    """用 LLM 做意图分类，失败或结果未知返回空串"""
    try:
        from langchain_core.messages import HumanMessage
        choices = "\n".join(f"- {k}：{v}" for k, v in _INTENT_HINTS.items())
        resp = _get_llm_classifier().invoke([
            HumanMessage(content=_INTENT_PROMPT.format(choices=choices, text=text)),
        ])
        label = (resp.content or "").strip().lower()
        for k in _INTENT_HINTS:
            if k in label:
                return k
        logger.warning(f"[RobotGraph] LLM 意图分类返回未知结果: {label!r}")
    except Exception as e:
        logger.warning(f"[RobotGraph] LLM 意图分类失败，回退规则: {e}")
    return ""


def route_intent(state: RobotState) -> str:
    text = (state.get("text") or "").strip()
    if not text:
        return "help"
    # ---- 快速通道：模式唯一/意图明确，零成本不经 LLM ----
    if any(k in text for k in ("帮助", "菜单", "功能", "help", "hello", "你好")):
        return "help"
    if any(k in text for k in ("录入工单", "新增工单", "创建工单", "工单录入", "报修")):
        return "create"
    # 工单号查询：WO-YYYYMMDD-XXX 或 6 位以上纯数字
    if re.search(r"WO[-_ ]?[\d-]{6,}", text, re.IGNORECASE) or re.search(r"\d{6,}", text):
        return "workorder"
    # ---- LLM 分类：处理 todo / duty / inventory / repair 等自然语言 ----
    label = _classify_intent_llm(text)
    if label:
        return label
    # ---- LLM 失败降级：规则兜底，默认追踪维修 ----
    if any(k in text for k in ("我的待办", "我的工单", "待办", "代办", "任务")):
        return "todo"
    if any(k in text for k in ("排班", "值班", "班表", "班次")):
        return "duty"
    try:
        from app.agents.answer_agent import answer_agent
        if answer_agent.is_inventory_query(text):
            return "inventory"
    except Exception as e:
        logger.warning(f"[RobotGraph] 库存意图判断异常，跳过: {e}")
    return "repair"


# ============================================================
# 主图意图节点
# ============================================================
def help_node(state: RobotState) -> dict:
    return {"reply": HELP_TEXT}


def none_node(state: RobotState) -> dict:
    """意图与所有功能无关：明确提示没有该功能并引导查看帮助"""
    return {"reply": (
        "抱歉，我暂时没有这个功能。\n"
        "我是维修助手，可以帮您：\n"
        "1. 输入工单号查询工单状态\n"
        "2. 发送「我的待办」查看名下待处理工单\n"
        "3. 发送「排班」/「我的排班」查询排班\n"
        "4. 发送「查备件库存」查询库存\n"
        "5. 发送设备名称或故障现象，我会引导您一步步排查\n"
        "发送「帮助」可查看完整功能说明。"
    )}


def create_node(state: RobotState) -> dict:
    return {"reply": _CREATE_WO_TEXT}


def todo_node(state: RobotState) -> dict:
    staff_id = state.get("staff_id") or ""
    user_id = state.get("user_id")
    if not user_id and not staff_id:
        return {"reply": "未识别到您的系统账号，请先登录系统在『安全设置』中绑定钉钉后再试。"}
    return {"reply": tools.query_my_workorders(staff_id)}


def inventory_node(state: RobotState) -> dict:
    return {"reply": tools.query_inventory(state.get("text") or "")}


def duty_node(state: RobotState) -> dict:
    return {"reply": tools.query_duty_schedule(state.get("staff_id") or "", state.get("text") or "")}


def repair_node(state: RobotState) -> dict:
    # 结构化追踪（联通复用追踪模式）：A/B/C 选项逐步排查；对话式 guided_repair_chat 保留给 MCP 工具
    return {"reply": tools.guided_repair_track(state.get("staff_id") or "", state.get("text") or "")}


# ============================================================
# 工单查询子图（normalize → query）
# ============================================================
def wo_normalize_node(state: WoSubState) -> dict:
    """从用户消息中提取工单号并规范化"""
    text = state.get("text") or ""
    m = re.search(r"WO[-_ ]?[\d-]{6,}", text, re.IGNORECASE) or re.search(r"\d{6,}", text)
    if not m:
        return {"wo_no": "", "reply": "请输入工单号，例如：WO-20260804-002"}
    no = m.group(0).upper()
    if "WO" not in no:
        no = f"WO-{no}"
    return {"wo_no": no}


def wo_query_node(state: WoSubState) -> dict:
    """按规范化后的工单号查询并格式化回复"""
    no = state.get("wo_no") or ""
    if not no:
        return {"reply": state.get("reply") or "请输入工单号，例如：WO-20260804-002"}
    return {"reply": tools.query_work_order(no)}


_wo_subgraph = StateGraph(WoSubState)
_wo_subgraph.add_node("normalize", wo_normalize_node)
_wo_subgraph.add_node("query", wo_query_node)
_wo_subgraph.set_entry_point("normalize")
_wo_subgraph.add_edge("normalize", "query")
_wo_subgraph.add_edge("query", END)
WO_SUBGRAPH = _wo_subgraph.compile()


# ============================================================
# 主图构建
# ============================================================
def build_robot_graph():
    graph = StateGraph(RobotState)
    graph.add_node("router", lambda s: {})  # 占位节点，实际分发由条件边完成
    graph.add_node("help", help_node)
    graph.add_node("create", create_node)
    graph.add_node("todo", todo_node)
    graph.add_node("inventory", inventory_node)
    graph.add_node("duty", duty_node)
    graph.add_node("repair", repair_node)
    graph.add_node("none", none_node)
    graph.add_node("workorder", WO_SUBGRAPH)  # 子图作为主图节点

    graph.set_entry_point("router")
    graph.add_conditional_edges(
        "router",
        route_intent,
        {
            "help": "help",
            "create": "create",
            "todo": "todo",
            "workorder": "workorder",
            "inventory": "inventory",
            "duty": "duty",
            "repair": "repair",
            "none": "none",
        },
    )
    for node in ("help", "create", "todo", "workorder", "inventory", "duty", "repair", "none"):
        graph.add_edge(node, END)
    return graph.compile()


ROBOT_GRAPH = build_robot_graph()


def invoke_robot(text: str, staff_id: str = "", user_id: Optional[int] = None, user_dt_userid: str = "") -> str:
    """钉钉机器人消息入口：执行 LangGraph 图，返回最终回复"""
    result = ROBOT_GRAPH.invoke({
        "text": text or "",
        "staff_id": staff_id or "",
        "user_id": user_id,
        "user_dt_userid": user_dt_userid or "",
    })
    reply = (result or {}).get("reply") or ""
    return reply or HELP_TEXT
