"""钉钉派工进度确认卡片
========================

流程：
1. 主管派工后，机器人给维修员推送互动卡片（工单信息 + 当前进度按钮）
2. 维修员点击按钮 → Stream 卡片回调（TOPIC_CARD_CALLBACK）→ 本模块处理：
   - 校验身份（回调人 = 被指派维修员）
   - 复用 _do_transition 更新工单状态 + 写进度日志
   - 刷新卡片为下一步按钮
   - 给主管的钉钉发送进度通知
3. 进度事件点（与系统按钮一致）：
   确认接受 → 已到达 → 开始检查 → 开始维修 → 完成维修 → 确认工单录入
   - 「完成维修」仅通知主管，状态不变（维修员回系统填表单提交才算完成）
   - 「确认工单录入」引导维修员回系统完成表单录入
"""
from __future__ import annotations

import json
import threading
from typing import Dict, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.dingtalk_card import send_card, update_card, request_button
from app.core.dingtalk import dingtalk

# ============================================================
# 按钮动作定义
# ============================================================
ACTION_ACCEPT = "wo_accept"      # 确认接受
ACTION_ARRIVE = "wo_arrive"      # 已到达
ACTION_INSPECT = "wo_inspect"    # 开始检查
ACTION_REPAIR = "wo_repair"      # 开始维修
ACTION_FINISH = "wo_finish"      # 完成维修
ACTION_FORM = "wo_form"          # 确认工单录入

# action → (目标状态, 进度中文, 主管通知文案)
ACTION_MAP = {
    ACTION_ACCEPT: ("ACCEPTED", "确认接受", "确认接受"),
    ACTION_ARRIVE: ("ARRIVED", "已到达现场", "已到达现场"),
    ACTION_INSPECT: ("INSPECTING", "开始检查", "开始检查"),
    ACTION_REPAIR: ("IN_PROGRESS", "开始维修", "开始维修"),
}

# 按钮文字 → 动作。MarkdownButton 模板回调不保留自定义 params.id，
# 只回传按钮文字（params.text），因此按文字反查动作。
_TEXT_TO_ACTION = {
    "确认接受": ACTION_ACCEPT,
    "已到达": ACTION_ARRIVE,
    "开始检查": ACTION_INSPECT,
    "开始维修": ACTION_REPAIR,
    "完成维修": ACTION_FINISH,
    "确认工单录入": ACTION_FORM,
    "查看进度": ACTION_FORM,
}

# 各状态下一步的按钮
_NEXT_BUTTONS = {
    "ASSIGNED": request_button("确认接受", ACTION_ACCEPT),
    "ACCEPTED": request_button("已到达", ACTION_ARRIVE),
    "ARRIVED": request_button("开始检查", ACTION_INSPECT),
    "INSPECTING": request_button("开始维修", ACTION_REPAIR),
    "IN_PROGRESS": request_button("完成维修", ACTION_FINISH, "orange"),
}


def _status_cn(status: Optional[str]) -> str:
    return {
        "DRAFT": "草稿",
        "SUBMITTED": "待派工",
        "ASSIGNED": "待接受",
        "ACCEPTED": "已接单",
        "ARRIVED": "已到达",
        "INSPECTING": "检查中",
        "IN_PROGRESS": "维修中",
        "ARCHIVING": "待归档",
        "ARCHIVED": "已归档",
        "COMPLETED": "已完成",
    }.get(status or "", status or "-")


def _device_text(wo) -> str:
    device = ""
    try:
        if getattr(wo, "device", None):
            device = wo.device.device_name or wo.device.device_code or ""
    except Exception:
        pass
    return device or (wo.device_code or "-")


def _card_markdown(wo, public_url: str = "") -> str:
    sup = ""
    try:
        from app.models.user import User
        db = SessionLocal()
        try:
            creator = db.query(User).filter(User.id == wo.created_by).first()
            if creator:
                sup = f"\n**派工人**：{creator.real_name}"
        finally:
            db.close()
    except Exception:
        pass
    link = f"\n\n[点击进入系统查看工单]({public_url.rstrip('/')}/#/work-orders/{wo.id})" if public_url else ""
    return (
        f"**工单编号**：{wo.work_order_no}\n"
        f"**设备**：{_device_text(wo)}\n"
        f"**故障描述**：{(wo.fault_description or '')[:100]}\n"
        f"**当前进度**：{_status_cn(wo.status.value if wo.status else None)}"
        f"{sup}{link}"
    )


def _get_work_order(db: Session, out_track_id: str):
    from app.models.work_order import WorkOrder
    return db.query(WorkOrder).filter(WorkOrder.work_order_no == out_track_id).first()


def _get_user_by_dtuserid(db: Session, dt_userid: str):
    from app.models.user import User
    return db.query(User).filter(User.dingtalk_userid == dt_userid).first()


def _notify_supervisor(db: Session, wo, action_cn: str, technician_name: str) -> None:
    """给主管（工单创建者）发钉钉进度通知"""
    from app.models.user import User
    sup = db.query(User).filter(User.id == wo.created_by).first()
    if not sup or not sup.dingtalk_userid:
        logger.info(f"[WoCard] 主管未绑定钉钉，跳过进度通知: wo={wo.work_order_no}")
        return
    content = (
        f"**工单进度更新**\n\n"
        f"**工单编号**：{wo.work_order_no}\n"
        f"**维修员**：{technician_name}\n"
        f"**进度**：{action_cn}\n"
        f"**设备**：{_device_text(wo)}"
    )
    dingtalk.send_work_notice(sup.dingtalk_userid, f"进度更新: {wo.work_order_no}", content)
    logger.info(f"[WoCard] 已通知主管 {sup.real_name}: {wo.work_order_no} {action_cn}")


# ============================================================
# 异步辅助：卡片刷新 / 主管通知放后台线程，避免阻塞回调与接口响应
# （钉钉 update_card / send_work_notice 为同步 HTTP 调用，耗时较长）
# ============================================================
def _refresh_card_async(wo_id: int, out_track_id: str, extra_markdown: str = "") -> None:
    """后台线程按工单最新状态刷新卡片"""
    def _worker():
        db = SessionLocal()
        try:
            from app.models.work_order import WorkOrder
            wo = db.query(WorkOrder).filter(WorkOrder.id == wo_id).first()
            if wo:
                _refresh_card(wo, out_track_id, extra_markdown)
        except Exception as e:
            logger.warning(f"[WoCard] 异步刷新卡片失败: {e}")
        finally:
            db.close()
    threading.Thread(target=_worker, daemon=True).start()


def _notify_supervisor_async(wo_id: int, action_cn: str, technician_name: str) -> None:
    """后台线程给主管发送钉钉进度通知"""
    def _worker():
        db = SessionLocal()
        try:
            from app.models.work_order import WorkOrder
            wo = db.query(WorkOrder).filter(WorkOrder.id == wo_id).first()
            if wo:
                _notify_supervisor(db, wo, action_cn, technician_name)
        except Exception as e:
            logger.warning(f"[WoCard] 异步通知主管失败: {e}")
        finally:
            db.close()
    threading.Thread(target=_worker, daemon=True).start()


# ============================================================
# 发送 / 更新进度卡片
# ============================================================
def send_progress_card(
    technician_userid: str,
    wo,
    supervisor_name: str = "",
    public_url: str = "",
) -> str:
    """主管派工后给维修员发送进度确认卡片。返回 out_track_id（失败时为空字符串）。"""
    if not technician_userid:
        logger.info(f"[WoCard] 维修员未绑定钉钉，跳过卡片: 工单{wo.work_order_no}")
        return ""
    status = wo.status.value if wo.status else "ASSIGNED"
    title = f"派工通知: {wo.work_order_no}"
    markdown = _card_markdown(wo, public_url)
    buttons = [_NEXT_BUTTONS.get(status, request_button("查看进度", ACTION_FORM, "gray"))]
    oid, err = send_card(technician_userid, title, markdown, buttons, out_track_id=wo.work_order_no)
    if not oid or err:
        # 可能已有同 outTrackId 的卡片实例 → 尝试更新
        ok = update_card(wo.work_order_no, title, markdown, buttons)
        if not ok:
            logger.error(f"[WoCard] 派工卡片发送失败: {err}")
            return ""
    logger.info(f"[WoCard] 派工进度卡片已发送: {wo.work_order_no} → 状态 {status}")
    return oid


def _refresh_card(wo, out_track_id: str, extra_markdown: str = "") -> None:
    """根据当前状态刷新卡片按钮"""
    status = wo.status.value if wo.status else None
    if status == "COMPLETED":
        update_card(out_track_id, f"工单完成: {wo.work_order_no}", _card_markdown(wo), [])
        return
    if status == "ARCHIVING":
        markdown = _card_markdown(wo) + "\n\n> 维修已完成，请在系统『维修报表』完善表单后完成工单归档。"
        update_card(out_track_id, f"待归档: {wo.work_order_no}", markdown, [])
        return
    if status == "ARCHIVED":
        update_card(out_track_id, f"已归档: {wo.work_order_no}", _card_markdown(wo), [])
        return
    btn = _NEXT_BUTTONS.get(status)
    if btn is None:
        return
    markdown = _card_markdown(wo)
    if extra_markdown:
        markdown += f"\n\n> {extra_markdown}"
    update_card(out_track_id, f"派工通知: {wo.work_order_no}", markdown, [btn])


# ============================================================
# 卡片回调处理
# ============================================================
def handle_card_callback(payload: Dict) -> Optional[str]:
    """处理派工进度卡片按钮回调，返回需回复维修员的文字（可能为 None）"""
    try:
        out_track_id = payload.get("outTrackId") or ""
        user_id = payload.get("userId") or ""
        content = payload.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except Exception:
                content = {}
        if not isinstance(content, dict):
            content = {}
        private = content.get("cardPrivateData") or {}
        params = private.get("params") or {}
        action = str(params.get("id") or "")
        if not action:
            # MarkdownButton 模板不保留自定义 params.id，按按钮文字反查动作
            action = _TEXT_TO_ACTION.get(str(params.get("text") or ""), "")
        if not action:
            action_ids = private.get("actionIds") or content.get("actionIds") or []
            action = action_ids[0] if action_ids else ""
        if not out_track_id or not action:
            logger.info(f"[WoCard] 回调缺参: outTrackId={out_track_id} action={action} userId={user_id}")
            return None
        logger.info(f"[WoCard] 回调: wo={out_track_id} action={action} userId={user_id}")
        return _dispatch_action(out_track_id, user_id, action)
    except Exception as e:
        logger.exception(f"[WoCard] 回调处理异常: {e}")
        return None


def _dispatch_action(out_track_id: str, user_id: str, action: str) -> Optional[str]:
    db = SessionLocal()
    try:
        wo = _get_work_order(db, out_track_id)
        if not wo:
            return f"未找到工单 {out_track_id}，请确认工单号。"
        tech = _get_user_by_dtuserid(db, user_id)
        if not tech:
            return "无法识别您的身份，请先在系统『安全设置』中绑定钉钉账号。"
        is_assigned = (wo.technician_id == tech.id) or (wo.assignee_id == tech.id)
        if not is_assigned and tech.role not in ("ADMIN",):
            return "该工单不是指派给您的，无法确认进度。"

        # ---- 确认工单录入：引导回系统 ----
        if action == ACTION_FORM:
            return (
                f"工单 **{wo.work_order_no}** 维修已完成。\n"
                f"请登录系统在『维修报表』中打开该工单，填写维修结果并提交，提交后自动收录知识库。"
            )

        # ---- 完成维修：工单进入待归档（ARCHIVING），引导回系统完善表单并归档 ----
        if action == ACTION_FINISH:
            cur_status = wo.status.value if wo.status else None
            if cur_status == "ARCHIVING":
                return (
                    f"工单 **{wo.work_order_no}** 已完成维修并处于待归档状态。\n"
                    f"请回系统『维修报表』完善表单，完成『工单归档』与『归档完成』。"
                )
            from app.api.work_orders import _do_transition
            from app.schemas import WorkOrderTransition
            try:
                _do_transition(wo.id, WorkOrderTransition(to_status="ARCHIVING", source="DINGTALK_CARD"), db, tech)
            except Exception as e:
                detail = getattr(e, "detail", str(e))
                logger.warning(f"[WoCard] 完成维修流转失败 wo={wo.work_order_no}: {detail}")
                return f"❌ 操作失败: {detail}"
            _refresh_card_async(wo.id, out_track_id, "维修已完成，请在系统完成表单录入并提交归档。")
            _notify_supervisor_async(wo.id, "完成维修（待归档）", tech.real_name or tech.username)
            return (
                f"✅ 已记录维修完成，工单进入【待归档】。\n"
                f"请回系统『维修报表』打开工单 {wo.work_order_no}，完善表单后完成『工单归档』，"
                f"最后点击『归档完成』（需完成度达标）。"
            )

        # ---- 常规进度推进（复用系统状态机） ----
        target = ACTION_MAP.get(action)
        if not target:
            return f"未知操作: {action}"
        to_status, status_cn, notify_text = target

        # 幂等保护：状态已到目标则不再重复流转/通知（防止按钮重复点击或回调重投）
        cur_status = wo.status.value if wo.status else None
        if cur_status == to_status:
            logger.info(f"[WoCard] 重复回调已拦截: {wo.work_order_no} 已处于 {to_status}")
            return f"工单 {wo.work_order_no} 已处于【{status_cn}】状态，无需重复操作。"

        from app.api.work_orders import _do_transition
        from app.schemas import WorkOrderTransition
        transition_data = WorkOrderTransition(to_status=to_status, source="DINGTALK_CARD")
        try:
            _do_transition(wo.id, transition_data, db, tech)
        except Exception as e:
            detail = getattr(e, "detail", str(e))
            logger.warning(f"[WoCard] 流转失败 wo={wo.work_order_no} → {to_status}: {detail}")
            return f"❌ 操作失败: {detail}"

        # 异步刷新卡片为下一步 + 异步通知主管（不阻塞回调响应）
        _refresh_card_async(wo.id, out_track_id)
        _notify_supervisor_async(wo.id, notify_text, tech.real_name or tech.username)
        logger.info(f"[WoCard] 进度确认成功: {wo.work_order_no} → {to_status} by {tech.real_name}")
        return f"✅ 工单 {wo.work_order_no} 已【{status_cn}】，进度已同步给主管。"
    finally:
        db.close()
