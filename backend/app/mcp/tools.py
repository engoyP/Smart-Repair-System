"""MCP 工具函数（业务逻辑唯一实现）

钉钉机器人直接调用本模块函数（低延迟，无网络往返），
MCP Server 也通过本模块暴露同样的工具给外部 AI 客户端，保证单一来源。
"""
from __future__ import annotations

import time
import threading
import uuid
import re
import json
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List

from loguru import logger

from app.core.database import SessionLocal
from app.models.user import User
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.knowledge import KnowledgeItem
from app.models.duty_schedule import DutySchedule

# 工单状态 → 中文
STATUS_CN = {
    "DRAFT": "草稿",
    "SUBMITTED": "待审核",
    "ASSIGNED": "已指派",
    "ACCEPTED": "已接单",
    "ARRIVED": "已到场",
    "INSPECTING": "检修中",
    "IN_PROGRESS": "维修中",
    "ARCHIVING": "待归档",
    "ARCHIVED": "已归档",
    "COMPLETED": "已完成",
    "REJECTED": "已驳回",
    "STANDARDIZED": "已标准化",
    "CLASSIFIED": "已分类",
    "APPROVED": "已审核",
}

# 进行中的状态（用于"我的待办"）
ACTIVE_STATUS = (
    WorkOrderStatus.SUBMITTED,
    WorkOrderStatus.ASSIGNED,
    WorkOrderStatus.ACCEPTED,
    WorkOrderStatus.ARRIVED,
    WorkOrderStatus.INSPECTING,
    WorkOrderStatus.IN_PROGRESS,
    WorkOrderStatus.ARCHIVING,
)


def _status_cn(status) -> str:
    raw = status.value if hasattr(status, "value") else str(status)
    return STATUS_CN.get(raw, raw)


def _normalize_work_order_no(raw: str) -> str:
    """将用户各种输入（WO-YYYYMMDD-XXX / WOYYYYMMDDXXX / 纯数字）规范化为 WO-YYYYMMDD-XXX"""
    no = (raw or "").strip().upper().replace(" ", "").replace("_", "-")
    if not no:
        return no
    m = re.match(r"WO-?(\d{8})-?(\d+)$", no)
    if m:
        return f"WO-{m.group(1)}-{m.group(2)}"
    if no.startswith("WO") and re.match(r"WO-?\d{4,}$", no):
        return no.replace("WO", "WO-", 1) if no.startswith("WO") and no[2] != "-" else no
    return no


# ============================================================
# 1. 知识检索（智能工具，可能耗时数秒~十几秒）
# ============================================================
def search_knowledge(query: str) -> str:
    """按系统 /answer 底层逻辑检索：双库检索 → RRF 融合 → 严格过滤重排 → AnswerAgent 回答

    走公共编排层 app.agents.retrieval_flow（与智能问答/专家模式同一套检索逻辑，保证策略一致）。
    """
    if not query or not query.strip():
        return "请输入故障描述，例如：注塑机 温度过高"
    try:
        from app.agents.retrieval_flow import retrieve_hybrid, extract_device_and_fault, filter_rerank_cases
        from app.agents.answer_agent import answer_agent

        merged, error_codes, tools = retrieve_hybrid(query, top_k=10)
        device, kws = extract_device_and_fault(tools, query)
        cases = filter_rerank_cases(
            tools, merged, query, top_n=5,
            require_device=device, require_keywords=tuple(kws),
            error_codes=error_codes,
        )
        result = answer_agent.answer(query, cases)
        return result.answer
    except Exception as e:
        logger.warning(f"[MCP] 知识检索失败: {e}")
        return "知识检索暂时不可用，请稍后再试或直接联系资深工程师。"


# ============================================================
# 1.1 追踪维修（对话式引导，逐步排查）
# ============================================================
_GUIDED_LOCK = threading.Lock()
# staff 映射持久化到 Redis（与 guided_repair_agent 会话共用），重启/多进程不丢失
_GUIDED_SESSION_KEY_PREFIX = "mcp/staff_guid:session:"   # staff_id -> guided session_id
_GUIDED_LAST_KEY_PREFIX = "mcp/staff_guid:last:"          # staff_id -> 最后活动时间戳
GUIDED_SESSION_TTL = 24 * 3600  # 24 小时无对话则开启新会话，覆盖跨班次/跨天排查，避免跨故障串话


def guided_repair_chat(staff_id: str, message: str) -> str:
    """追踪维修模式：按钉钉用户维护多轮会话，逐步引导排查（每轮只给【分析】+【操作】一步）"""
    if not message or not message.strip():
        return "请输入故障现象，例如：PLC 输入输出通道无响应"
    if not staff_id:
        return "缺少用户标识（钉钉企业 userId），无法维护排查会话。"
    from app.agents.guided_repair_agent import guided_repair_agent
    from app.core.cache_service import cache_service

    now = time.time()
    # 从 Redis 读取该用户已有会话（Redis 不可用时 cache_service 自动降级内存）
    try:
        session_id = cache_service.get(f"{_GUIDED_SESSION_KEY_PREFIX}{staff_id}")
        last = cache_service.get(f"{_GUIDED_LAST_KEY_PREFIX}{staff_id}") or 0.0
    except Exception as e:
        logger.warning(f"[MCP] 会话映射读取失败: {e}")
        session_id, last = None, 0.0
    with _GUIDED_LOCK:
        if session_id is None or (now - float(last)) > GUIDED_SESSION_TTL:
            session_id = str(uuid.uuid4())[:8]
            cache_service.set(f"{_GUIDED_SESSION_KEY_PREFIX}{staff_id}", session_id, ttl=GUIDED_SESSION_TTL)
        cache_service.set(f"{_GUIDED_LAST_KEY_PREFIX}{staff_id}", now, ttl=GUIDED_SESSION_TTL)
    try:
        return guided_repair_agent.chat_sync(session_id, message)
    except Exception as e:
        logger.warning(f"[MCP] 追踪维修对话失败: {e}")
        return "追踪维修暂时不可用，请稍后再试或直接联系资深工程师。"


# ============================================================
# 1.2 追踪维修（结构化）：钉钉问答联通复用追踪模式
# 复用 guided_repair_agent.start_diagnosis / next_step 的 A/B/C 选项逐步排查，
# 解析用户操作反馈（选X + 动作 + 状态）续接 next_step；解析失败重发格式指引，不新开会话。
# ============================================================
_ACTION_FEEDBACK_RE = re.compile(r"选(?:了)?\s*([A-Ca-c0-9一二三①-⑨])")
_ACTION_LEADING_RE = re.compile(r"^([A-Ca-c0-9一二三①-⑨])\s*[\s,，。、:：]")
_OPTION_ALIAS = {
    "1": "A", "2": "B", "3": "C",
    "一": "A", "二": "B", "三": "C",
    "①": "A", "②": "B", "③": "C",
    "a": "A", "b": "B", "c": "C",
}
_STATUS_CONNECTOR_RE = re.compile(r"(?:结果|现在|目前|然后|之后|发现|试机|现在设备|设备状态)")
# 已解决 / 未解决判定：未解决词优先，避免"还不行/不可以"误命中"行/可以"造成反向判断
_UNSOLVED_KW = ("不行", "不可以", "没反应", "没变化", "没解决", "没恢复", "没效果", "没用", "无效", "还异常", "仍异常", "依旧")
_SOLVED_KW = ("解决", "正常", "恢复", "好了", "可以", "完成", "ok", "没问题", "修复")
_NEW_FAULT_HINTS = ("新问题", "重新开始", "另一个故障", "换个故障", "另外的故障", "别的故障")

_parser_llm = None


def _get_parser_llm():
    """懒加载反馈解析 LLM（非流式、低温度、短超时，失败不阻塞）"""
    global _parser_llm
    if _parser_llm is None:
        from langchain_openai import ChatOpenAI
        from app.core.config import settings
        _parser_llm = ChatOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
            temperature=0,
            timeout=15,
            max_retries=1,
        )
    return _parser_llm


def _map_option(raw: str, current_options: List[Dict]) -> str:
    """把用户写的选项（A/B/C 或 ①②③/123/一二三）映射为选项 id；无法映射返回空串"""
    key = raw.strip().lower()
    if key in _OPTION_ALIAS:
        return _OPTION_ALIAS[key]
    if current_options:
        try:
            idx = ["a", "b", "c"].index(key)
            return current_options[idx]["id"]
        except (ValueError, IndexError, KeyError):
            pass
    return key.upper() if len(key) == 1 else ""


def _split_action_status(rest: str) -> tuple:
    """把反馈剩余文本切成（动作, 设备状态）：按状态连接词切分；无连接词则按解决词判定，整体作动作"""
    m = _STATUS_CONNECTOR_RE.search(rest)
    if m:
        action = rest[:m.start()].strip() or "已执行该选项"
        status = rest[m.start():].strip() or "已执行"
        return action, status
    if any(kw in rest for kw in _UNSOLVED_KW):
        return rest or "已执行该选项", "仍异常"
    if any(kw in rest for kw in _SOLVED_KW):
        return rest or "已执行该选项", "恢复正常"
    return rest or "已执行该选项", "已执行"


def _llm_parse_feedback(message: str, current_options: List[Dict]) -> Optional[Dict]:
    """LLM 兜底解析反馈三字段：仅当正则快路取不到选项时调用"""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        opts_text = "、".join(f"{o.get('id', '')}({o.get('cause', '')})" for o in current_options) or "未知"
        sys = ("你是设备维修排查的反馈解析器。用户回复了排查操作反馈，抽取三个字段并只输出 JSON：\n"
               '{"selected_option": "A", "action_taken": "执行的操作", "device_status": "执行后设备状态"}')
        usr = (f"当前排查选项：{opts_text}\n用户消息：{message}\n"
               "规则：selected_option 从当前选项里选最接近的 id，找不到就返回空串；"
               "action_taken / device_status 尽量用消息原文。")
        resp = _get_parser_llm().invoke([SystemMessage(content=sys), HumanMessage(content=usr)])
        text = resp.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        if isinstance(data, dict) and data.get("action_taken"):
            return {
                "selected_option": data.get("selected_option") or "",
                "action_taken": str(data.get("action_taken", "")),
                "device_status": str(data.get("device_status", "")),
            }
    except Exception as e:
        logger.warning(f"[MCP] 反馈 LLM 解析失败: {e}")
    return None


def _parse_action_feedback(message: str, current_options: List[Dict]) -> Optional[Dict]:
    """从用户自由文本解析追踪反馈（selected_option / action_taken / device_status）

    正则快路：取「选X」或句首选项字母 → 切分动作/状态；取不到选项才走 LLM 兜底。
    返回 None 表示无法解析（上层重发格式指引，不新开会话）。
    """
    text = (message or "").strip()
    if not text:
        return None
    opt, rest = "", text
    m = _ACTION_FEEDBACK_RE.search(text)
    if m:
        opt = _map_option(m.group(1), current_options)
        rest = text[m.end():].strip()
    else:
        m2 = _ACTION_LEADING_RE.match(text)
        if m2:
            opt = _map_option(m2.group(1), current_options)
            rest = text[m2.end():].strip()
    if opt:
        action, status = _split_action_status(rest)
        return {"selected_option": opt, "action_taken": action, "device_status": status}
    return _llm_parse_feedback(text, current_options)


def _render_guided_step_text(step) -> str:
    """把 GuidedRepairStep 渲染为钉钉 markdown 文本（A/B/C 选项 + 回复指引）"""
    if step.status == "completed":
        parts = [f"**排查结束 · 第 {step.step} 步**"]
        if step.message:
            parts.append("")
            parts.append(step.message)
        if step.summary:
            parts.append("")
            parts.append(step.summary)
        return "\n".join(parts)
    parts = [f"**第 {step.step} 步 · 排查方向**"]
    if step.message:
        parts.append("")
        parts.append(step.message)
    if step.options:
        parts.append("")
        parts.append("【下一步选项】")
        for o in step.options:
            parts.append(f"**{o.id}** {o.cause}")
            if o.diagnostic_action:
                parts.append(f"　→ {o.diagnostic_action}")
        parts.append("")
        parts.append("请按格式回复：**选选项 + 执行的操作 + 执行后设备状态**")
        parts.append("例如：选A 测量了电机电压 恢复正常")
        parts.append("排查另一个故障，回复「新问题」")
    return "\n".join(parts)


def guided_repair_track(staff_id: str, message: str) -> str:
    """追踪维修（结构化）：钉钉问答联通复用追踪模式

    每 staff 维护一个结构化会话：
    - 无会话 / 已结束 / 会话过期 → start_diagnosis 开新会话，给 A/B/C 选项
    - 进行中 → 解析操作反馈走 next_step；解析失败重发格式指引；显式「新问题」开新会话
    """
    if not message or not message.strip():
        return "请输入故障现象，例如：注塑机温度过高、空压机不启动。"
    if not staff_id:
        return "缺少用户标识（钉钉企业 userId），无法维护排查会话。"
    from app.agents.guided_repair_agent import guided_repair_agent
    from app.core.cache_service import cache_service

    now = time.time()
    try:
        session_id = cache_service.get(f"{_GUIDED_SESSION_KEY_PREFIX}{staff_id}")
        last = cache_service.get(f"{_GUIDED_LAST_KEY_PREFIX}{staff_id}") or 0.0
    except Exception as e:
        logger.warning(f"[MCP] 会话映射读取失败: {e}")
        session_id, last = None, 0.0

    # ---- 进行中的结构化会话：续接 / 重发指引 / 显式新问题 ----
    if session_id and (now - float(last)) <= GUIDED_SESSION_TTL:
        status, is_structured = guided_repair_agent.get_session_status(session_id)
        if status == "diagnosing" and is_structured:
            if any(h in message for h in _NEW_FAULT_HINTS):
                session_id = None  # 显式新问题 → 走下方开新会话
            else:
                current_options = guided_repair_agent.get_current_options(session_id)
                feedback = _parse_action_feedback(message, current_options)
                if feedback:
                    try:
                        step = guided_repair_agent.next_step(
                            session_id,
                            selected_option=feedback["selected_option"],
                            action_taken=feedback["action_taken"],
                            device_status=feedback["device_status"],
                        )
                    except Exception as e:
                        logger.error(f"[MCP] 追踪下一步失败: {e}")
                        return "步骤生成失败，请稍后再试或回复「新问题」重新开始排查。"
                    cache_service.set(f"{_GUIDED_LAST_KEY_PREFIX}{staff_id}", now, ttl=GUIDED_SESSION_TTL)
                    return _render_guided_step_text(step)
                return ("这条消息我没能识别为排查反馈。请按格式回复：**选选项 + 执行的操作 + 执行后设备状态**\n"
                        "例如：选A 测量了电机电压 恢复正常\n"
                        "排查另一个故障，回复「新问题」重新开始。")

    # ---- 新会话 / 已结束 / 会话过期 → 开新结构化诊断 ----
    with _GUIDED_LOCK:
        step = guided_repair_agent.start_diagnosis(message, device_type="")
        new_sid = step.session_id
        if new_sid:
            cache_service.set(f"{_GUIDED_SESSION_KEY_PREFIX}{staff_id}", new_sid, ttl=GUIDED_SESSION_TTL)
        cache_service.set(f"{_GUIDED_LAST_KEY_PREFIX}{staff_id}", now, ttl=GUIDED_SESSION_TTL)
    return _render_guided_step_text(step)


# ============================================================
# 2. 工单查询
# ============================================================
def query_work_order(work_order_no: str) -> str:
    """按工单号查询工单状态、设备、维修员、进度"""
    if not work_order_no or not work_order_no.strip():
        return "请输入工单号，例如：WO-20260804-002"
    no = _normalize_work_order_no(work_order_no)
    db = SessionLocal()
    try:
        wo = db.query(WorkOrder).filter(WorkOrder.work_order_no == no).first()
        if not wo:
            return f"未找到工单 {no}，请确认工单号是否正确。"
        status = _status_cn(wo.status)
        tech = None
        if wo.technician_id:
            tech = db.query(User).filter(User.id == wo.technician_id).first()
        lines = [
            f"### 工单 {wo.work_order_no}",
            f"- 设备：{wo.device_code or '-'}",
            f"- 故障：{wo.fault_description or '-'}",
            f"- 状态：**{status}**",
            f"- 优先级：{wo.priority or 'MEDIUM'}",
            f"- 维修员：{tech.real_name if tech else '-'}",
        ]
        if wo.location:
            lines.append(f"- 位置：{wo.location}")
        if wo.progress_logs:
            last = wo.progress_logs[-1]
            lines.append(f"- 最新进度：{last.remark or ''}")
        return "\n".join(lines)
    finally:
        db.close()


# ============================================================
# 3. 我的待办（按钉钉企业 userId 识别用户）
# ============================================================
def query_my_workorders(staff_id: str) -> str:
    """查询指定钉钉用户（企业 userId）名下待处理工单列表"""
    if not staff_id:
        return "缺少用户标识（钉钉企业 userId / senderStaffId）。"
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.dingtalk_userid == staff_id).first()
        if not user:
            return "未识别到该系统用户，请先在系统中绑定钉钉账号。"
        wos = (
            db.query(WorkOrder)
            .filter(WorkOrder.technician_id == user.id, WorkOrder.status.in_(ACTIVE_STATUS))
            .order_by(WorkOrder.created_at.desc())
            .limit(10)
            .all()
        )
        if not wos:
            return "您名下暂时没有待处理的工单。"
        lines = [f"您名下共有 **{len(wos)}** 个待处理工单：", ""]
        for wo in wos:
            lines.append(f"- {wo.work_order_no}｜{wo.fault_description or '-'}｜{_status_cn(wo.status)}")
        lines.append("")
        lines.append("回复工单号可查看详情。")
        return "\n".join(lines)
    finally:
        db.close()


# ============================================================
# 3.5 排班查询
# ============================================================
_SHIFT_CN = {"MORNING": "早班", "AFTERNOON": "中班", "NIGHT": "夜班"}
_LEAVE_TYPE_CN = {
    "ANNUAL": "年假",
    "SICK": "病假",
    "PERSONAL": "事假",
    "COMPENSATION": "调休",
    "MARRIAGE": "婚假",
    "MATERNITY": "产假",
    "FUNERAL": "丧假",
    "OTHER": "其他",
}


def _parse_duty_date(text: str) -> date:
    """从消息中解析排班日期（支持 今天/明天/后天/YYYY-MM-DD/X月X日），默认今天"""
    today = datetime.now().date()
    t = (text or "").strip()
    if "后天" in t:
        return today + timedelta(days=2)
    if "明天" in t:
        return today + timedelta(days=1)
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日号]?", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", t)
    if m:
        try:
            return date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    return today


def query_duty_schedule(staff_id: str, text: str = "") -> str:
    """排班查询：'我的排班'查本人近 7 天；含日期查指定日期排班（按班次分组）；默认查今日"""
    db = SessionLocal()
    try:
        target = _parse_duty_date(text)
        # 我的排班：按天聚合展示未来 7 个自然日（当天重复班次合并、请假合并显示）
        if any(k in (text or "") for k in ("我的排班", "我的班", "我的值班", "我的排班情况")):
            user = db.query(User).filter(User.dingtalk_userid == staff_id).first()
            if not user:
                return "未识别到您的系统账号，请先登录系统在『安全设置』中绑定钉钉后再试。"
            today = datetime.now().date()
            end = today + timedelta(days=6)
            schedules = (
                db.query(DutySchedule)
                .filter(
                    DutySchedule.user_id == user.id,
                    DutySchedule.date >= today,
                    DutySchedule.date <= end,
                )
                .order_by(DutySchedule.date, DutySchedule.shift)
                .all()
            )
            if not schedules:
                return f"{user.real_name} 未来 7 天暂无排班记录。"
            by_day: Dict[date, List[DutySchedule]] = {}
            for s in schedules:
                by_day.setdefault(s.date, []).append(s)
            lines = [f"您（{user.real_name}）未来 7 天排班："]
            for d in sorted(by_day):
                items = by_day[d]
                leaves = [s for s in items if s.schedule_type == "LEAVE"]
                if leaves:
                    shifts = {s.shift for s in leaves}
                    if "ALL_DAY" in shifts or {"MORNING", "AFTERNOON"} <= shifts:
                        label = "全天请假"
                    else:
                        label = "、".join(_SHIFT_CN.get(sh, sh) for sh in sorted(shifts)) + "请假"
                    lv = leaves[0]
                    ltype = _LEAVE_TYPE_CN.get(lv.leave_type or "", lv.leave_type or "")
                    if ltype:
                        label = f"{label}（{ltype}）"
                else:
                    label = "、".join(_SHIFT_CN.get(s.shift, s.shift) for s in sorted(items, key=lambda x: x.shift))
                lines.append(f"- {d} {label}")
            return "\n".join(lines)
        # 指定日期 / 今日排班（按班次分组）
        items = (
            db.query(DutySchedule)
            .filter(DutySchedule.date == target)
            .order_by(DutySchedule.shift, DutySchedule.id)
            .all()
        )
        if not items:
            return f"{target} 暂无排班记录。"
        grouped = {"MORNING": [], "AFTERNOON": [], "NIGHT": []}
        for ds in items:
            name = ds.user.real_name if ds.user else f"#{ds.user_id}"
            if ds.schedule_type == "LEAVE":
                label = f"{name}（请假）"
            elif ds.note:
                label = f"{name}（{ds.note}）"
            else:
                label = name
            grouped.get(ds.shift, []).append(label)
        lines = [f"**{target} 排班**"]
        lines.append(f"早班：{'、'.join(grouped['MORNING']) or '无'}")
        lines.append(f"中班：{'、'.join(grouped['AFTERNOON']) or '无'}")
        lines.append(f"夜班：{'、'.join(grouped['NIGHT']) or '无'}")
        return "\n".join(lines)
    finally:
        db.close()


# ============================================================
# 4. 库存查询（智能工具）
# ============================================================
def query_inventory(question: str) -> str:
    """查询备件库存信息（备件名/编码/设备类型）"""
    if not question or not question.strip():
        return "请输入备件查询，例如：查一下保险丝的库存"
    db = SessionLocal()
    try:
        from app.agents.answer_agent import answer_agent
        result = answer_agent.handle_inventory_query(question.strip(), db)
        return result.answer
    finally:
        db.close()


# ============================================================
# 5. 用户信息
# ============================================================
def get_user_by_staff(staff_id: str) -> str:
    """按钉钉企业 userId 查询系统用户绑定信息"""
    if not staff_id:
        return "缺少用户标识（钉钉企业 userId）。"
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.dingtalk_userid == staff_id).first()
        if not user:
            return f"未找到绑定钉钉用户（staff_id={staff_id}）。"
        return (
            f"用户名：{user.username}\n"
            f"姓名：{user.real_name}\n"
            f"手机：{user.phone or '-'}\n"
            f"角色：{user.role.value if hasattr(user.role, 'value') else user.role}\n"
            f"部门：{user.department or '-'}\n"
            f"钉钉姓名：{user.dingtalk_name or '-'}\n"
            f"钉钉绑定：{'是' if user.dingtalk_userid else '否'}"
        )
    finally:
        db.close()


# ============================================================
# 6. 设备列表
# ============================================================
def get_device_list(keyword: str = "") -> str:
    """查询设备列表，支持按关键字（名称/编码/类型）过滤"""
    from app.models.device import Device
    db = SessionLocal()
    try:
        query = db.query(Device)
        kw = (keyword or "").strip()
        if kw:
            from sqlalchemy import or_
            like = f"%{kw}%"
            query = query.filter(or_(
                Device.device_name.ilike(like),
                Device.device_code.ilike(like),
                Device.device_type.ilike(like),
                Device.model.ilike(like),
            ))
        devices = query.order_by(Device.id.desc()).limit(20).all()
        if not devices:
            return f"未找到匹配「{kw}」的设备。" if kw else "设备库为空。"
        lines = [f"共 {len(devices)} 台设备：", ""]
        for d in devices:
            status = d.run_status or "UNKNOWN"
            lines.append(f"- {d.device_code}｜{d.device_name}｜{d.device_type or '-'}｜状态:{status}")
        return "\n".join(lines)
    finally:
        db.close()


# ============================================================
# 7. 知识库统计
# ============================================================
def get_knowledge_stats() -> str:
    """查询知识库条目统计（总量/发布/草稿等）"""
    db = SessionLocal()
    try:
        total = db.query(KnowledgeItem).count()
        published = db.query(KnowledgeItem).filter(KnowledgeItem.status == "PUBLISHED").count()
        draft = db.query(KnowledgeItem).filter(KnowledgeItem.status == "DRAFT").count()
        reviewing = db.query(KnowledgeItem).filter(KnowledgeItem.status == "UNDER_REVIEW").count()
        return f"知识库统计：总量 {total} 条｜已发布 {published}｜草稿 {draft}｜审核中 {reviewing}"
    finally:
        db.close()


# ============================================================
# 8. 工单统计
# ============================================================
def get_workorder_stats() -> str:
    """查询工单统计（总量/进行中/已完成）"""
    db = SessionLocal()
    try:
        total = db.query(WorkOrder).count()
        active = db.query(WorkOrder).filter(WorkOrder.status.in_(ACTIVE_STATUS)).count()
        completed = db.query(WorkOrder).filter(WorkOrder.status == WorkOrderStatus.COMPLETED).count()
        return f"工单统计：总量 {total} 张｜进行中 {active}｜已完成 {completed}"
    finally:
        db.close()


# 工具注册表：供 MCP Server 和测试使用
TOOLS: Dict[str, Dict] = {
    "search_knowledge": {
        "fn": search_knowledge,
        "description": "输入设备故障描述（如'注塑机 温度过高'），检索历史维修案例并生成分析回答。可能耗时数秒至十几秒。",
        "parameters": {"query": {"type": "string", "description": "设备故障描述", "required": True}},
    },
    "guided_repair_chat": {
        "fn": guided_repair_chat,
        "description": "追踪维修模式：按钉钉企业 userId 维护多轮会话，逐步引导维修员排查故障，每轮只给出一步【分析】+【操作】。输入用户最近发送的故障现象或上一步检查结果。可能耗时数秒至十几秒。",
        "parameters": {
            "staff_id": {"type": "string", "description": "钉钉企业 userId", "required": True},
            "message": {"type": "string", "description": "故障现象或上一步检查结果", "required": True},
        },
    },
    "query_work_order": {
        "fn": query_work_order,
        "description": "按工单号（如 WO-20260804-002）查询工单状态、设备、维修员和最新进度。",
        "parameters": {"work_order_no": {"type": "string", "description": "工单号", "required": True}},
    },
    "query_my_workorders": {
        "fn": query_my_workorders,
        "description": "按钉钉企业 userId（senderStaffId）查询该用户名下待处理工单列表。",
        "parameters": {"staff_id": {"type": "string", "description": "钉钉企业 userId", "required": True}},
    },
    "query_inventory": {
        "fn": query_inventory,
        "description": "输入备件问题（如'查一下保险丝的库存'），返回备件库存、安全库存与状态。可能耗时数秒。",
        "parameters": {"question": {"type": "string", "description": "备件查询问题", "required": True}},
    },
    "get_user_by_staff": {
        "fn": get_user_by_staff,
        "description": "按钉钉企业 userId 查询系统用户的绑定信息（姓名/手机/角色/部门）。",
        "parameters": {"staff_id": {"type": "string", "description": "钉钉企业 userId", "required": True}},
    },
    "get_device_list": {
        "fn": get_device_list,
        "description": "查询设备列表，可按关键字（名称/编码/类型）过滤。",
        "parameters": {"keyword": {"type": "string", "description": "设备关键字（可选）", "required": False}},
    },
    "get_knowledge_stats": {
        "fn": get_knowledge_stats,
        "description": "查询知识库条目统计（总量/已发布/草稿/审核中）。",
        "parameters": {},
    },
    "get_workorder_stats": {
        "fn": get_workorder_stats,
        "description": "查询工单统计（总量/进行中/已完成）。",
        "parameters": {},
    },
}
