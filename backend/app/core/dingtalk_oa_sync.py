"""
钉钉 OA 审批 → 本地系统同步 核心逻辑
====================================

职责：
 1. 收到审批事件（bpms_instance_change，不论是 Stream 模式还是 HTTP 回调模式推送）
 2. 调 processInstance 接口拉审批详情
 3. 解析表单控件值（按 LEAVE_FIELD_MAP 字段映射）
 4. 钉钉 userid → 本地 users.id（用 dingtalk_userid 字段匹配）
 5. 写入 leave_requests / leave_request_details （支持幂等：correlation_id=processInstanceId 防重复）
 6. 若审批通过 → 事务写 duty_schedules 请假记录 + 顶岗人排班（复用 leave_requests.py 的 approve 逻辑）

模板未建好 / processCode 未配置时：
 - 所有操作只打 INFO 日志，不落库，不报错
"""
from __future__ import annotations

import json
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List, Tuple

from loguru import logger
from sqlalchemy import and_, or_, cast
from sqlalchemy.types import Date as SA_Date
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.config import settings  # 默认密码 hash 等
from app.core.dingtalk import DingTalkClient
from app.core import dingtalk_oa_config as OA_CFG
from app.core import sys_config as sys_conf
from app.models.user import User, UserRole
from app.models.leave_request import (
    LeaveRequest, LeaveRequestDetail,
    LeaveType, LeaveRequestStatus, LeaveShift,
)
from app.models.duty_schedule import DutySchedule, ShiftType
from app.models.work_order import WorkOrder, WorkOrderStatus


# ============================================================
# 对外主入口：收到一个 OA 审批事件后的全流程
# ============================================================
def handle_oa_event(raw_event: Dict[str, Any]) -> Optional[LeaveRequest]:
    """处理一条 OA 审批事件（Stream / HTTP 模式共用入口）

    Args:
        raw_event: 钉钉推送的原始事件 JSON（已解包后的 dict，不需要解密）

    Returns:
        成功落库的 LeaveRequest（若跳过/忽略则返回 None）
    """
    if not raw_event:
        return None

    # 1. 解析事件类型
    #    旧版 HTTP 回调：EventType = "bpms_instance_change"
    #    新版 Stream SDK：resource = "/v1.0/event/bpms_instance_change/processCode/xxx/type/finish"
    #    （没有 EventType 字段，type 字段是 start/finish 不是事件类型）
    event_type = (
        raw_event.get("EventType")          # HTTP 回调格式
        or raw_event.get("eventType")       # Stream 格式 (snake_case)
        or ""
    )
    resource = raw_event.get("resource") or ""
    if not event_type and resource and "bpms_" in resource:
        parts = resource.strip("/").split("/")
        event_type = parts[2] if len(parts) > 2 else ""
    # 只关心审批单状态变更（bpms_instance_change）
    # 同时从 resource 和 event_type 两个字段匹配
    combined = f"{event_type} {resource}".lower()
    if "bpms_instance_change" not in combined and "bpms_instance_status_change" not in combined:
        logger.info(f"[OA-Sync] 忽略非审批变更事件: event_type={event_type} resource={resource[:80]}")
        return None

    # 2. 提取 processInstanceId + processCode
    pi_id: str = (
        raw_event.get("processInstanceId")
        or raw_event.get("process_instance_id")
        or (raw_event.get("data") or {}).get("processInstanceId")
        or ""
    )
    process_code: str = (
        raw_event.get("processCode")
        or raw_event.get("process_code")
        or (raw_event.get("data") or {}).get("processCode")
        or ""
    )
    if not pi_id:
        logger.warning(f"[OA-Sync] 审批事件缺少 processInstanceId，跳过: {raw_event}")
        return None

    # 3. 如果我们配置了专属的请假模板 processCode → 只处理这个，其他模板都跳过
    if OA_CFG.LEAVE_PROCESS_CODE and process_code and process_code != OA_CFG.LEAVE_PROCESS_CODE:
        logger.info(f"[OA-Sync] 非请假审批模板 (processCode={process_code})，跳过 (只处理 {OA_CFG.LEAVE_PROCESS_CODE})")
        return None

    # 4. 如果连 processCode 都没配置 → 打提醒日志，尝试继续拉详情（看是不是请假单），失败就跳过
    if not OA_CFG.LEAVE_PROCESS_CODE:
        logger.info(
            f"[OA-Sync] ⚠️ 尚未配置 DINGTALK_LEAVE_PROCESS_CODE，已收到审批单 {pi_id}。"
            "为避免误同步，本次仅拉详情打印日志，不落库。你建好请假模板后把 processCode 填到 .env。"
        )

    # 5. 拉取审批单详情
    client = DingTalkClient()
    try:
        detail = client.get_process_instance(pi_id)
    except Exception as e:
        logger.exception(f"[OA-Sync] 拉取审批单 {pi_id} 详情失败: {e}")
        return None

    # 6. 如果没有配置 processCode → 打印日志 + 直接返回（不落库，让你先看字段结构）
    if not OA_CFG.LEAVE_PROCESS_CODE:
        logger.info(
            f"[OA-Sync] 📝 审批单 {pi_id} 详情已拉到（未配置请假模板，不落库）：\n"
            "你可以用这个 JSON 在 .env 里填 LEAVE_FIELD_MAP / processCode。JSON 见下：\n"
            f"{json.dumps(detail, ensure_ascii=False, indent=2)[:3000]}"
        )
        return None

    # 7. 提取结果状态（COMPLETED=审批完成/通过, TERMINATED=被撤销, REJECTED=审批拒绝, RUNNING=审批中）
    #    result 字段可能是 dict（老版：{"processResult":"agree","remark":"xxx"}）也可能是字符串（新版API：直接"agree"/"refuse"）
    _result_raw = detail.get("result")
    _result_processResult: str = ""
    if isinstance(_result_raw, dict):
        _result_processResult = str(_result_raw.get("processResult") or "")
    elif isinstance(_result_raw, str):
        _result_processResult = _result_raw
    status = _result_processResult or detail.get("status") or ""
    logger.info(f"[OA-Sync] 审批单 {pi_id} 状态: {status}")

    # RUNNING 也先存一笔 PENDING 记录（后续 COMPLETED/REJECTED 会再更新），避免重复入库
    db_status_map = {
        "agree": LeaveRequestStatus.APPROVED.value,
        "completed": LeaveRequestStatus.APPROVED.value,
        "COMPLETED": LeaveRequestStatus.APPROVED.value,
        "pass": LeaveRequestStatus.APPROVED.value,
        "reject": LeaveRequestStatus.REJECTED.value,
        "REJECTED": LeaveRequestStatus.REJECTED.value,
        "refuse": LeaveRequestStatus.REJECTED.value,
        "terminate": LeaveRequestStatus.CANCELLED.value,
        "TERMINATED": LeaveRequestStatus.CANCELLED.value,
        "cancel": LeaveRequestStatus.CANCELLED.value,
        "running": LeaveRequestStatus.PENDING.value,
        "RUNNING": LeaveRequestStatus.PENDING.value,
    }
    target_status = db_status_map.get(status.lower() if isinstance(status, str) else "", LeaveRequestStatus.PENDING.value)

    # 8. 从审批详情里解析表单值
    try:
        form_values = _extract_form_values(detail)
    except Exception as e:
        logger.exception(f"[OA-Sync] 解析审批单 {pi_id} 表单失败: {e}")
        return None

    # 9. 申请人：钉钉 userid → 本地 user
    #    新版API返回 originatorUserId（驼峰），老版返回 originatorUserid（小写 d 结尾），或 originator 对象
    originator_ddid = (
        detail.get("originatorUserId")
        or detail.get("originatorUserid")
        or detail.get("originator_userid")
        or (isinstance(detail.get("originator"), dict) and detail["originator"].get("userid"))
        or (isinstance(detail.get("data"), dict) and detail["data"].get("originatorUserId"))
        or (isinstance(detail.get("data"), dict) and detail["data"].get("originatorUserid"))
        or ""
    )
    if not originator_ddid:
        logger.warning(f"[OA-Sync] 审批单 {pi_id} 缺少申请人 userid，跳过")
        return None

    # 10. 落库（带幂等：correlation_id = pi_id）
    db = SessionLocal()
    try:
        lr = _persist_leave_request(db, pi_id, detail, originator_ddid, form_values, target_status)
        return lr
    finally:
        db.close()


# ============================================================
# 内部实现
# ============================================================
def _extract_form_values(detail: Dict[str, Any]) -> Dict[str, Any]:
    """按 LEAVE_FIELD_MAP 从审批详情 → 我们的字段名

    钉钉表单控件字段一般在：
      detail["formComponentValues"][i]["name"] = 控件别名
      detail["formComponentValues"][i]["label"] = 控件中文名
      detail["formComponentValues"][i]["key"] / "bizAlias" / "id" = 控件唯一 key
      detail["formComponentValues"][i]["value"] = 控件值（字符串/对象/数组）

    说明：模板控件名是中文（请假类型/开始时间/结束时间/请假事由），
    这里用 4 种名字都能匹配上，不怕改模板里叫哪个别名。
    """
    raw_components = detail.get("formComponentValues") or detail.get("form_component_values") or []
    if not isinstance(raw_components, list):
        # 高级版或其他路径返回：detail.result.list[0].formComponentValues 这种
        if isinstance(detail.get('result'), dict) and isinstance(detail['result'].get('list'), list):
            for it in detail['result']['list']:
                if isinstance(it, dict):
                    for kk in ('formComponentValues','form_component_values','form_details','components','form_items'):
                        if isinstance(it.get(kk), list):
                            raw_components = it[kk]
                            break
                    if raw_components:
                        break
        if not isinstance(raw_components, list):
            raw_components = []
    # 其他可能的键也扫一遍
    if not raw_components:
        for kk in ('form_details','formComponentList','formDetail','form_data','form_items','components'):
            if isinstance(detail.get(kk), list):
                raw_components = detail[kk]
                break
        if not raw_components and isinstance(detail.get('data'), dict):
            for kk in ('formComponentValues','form_details','formComponentList','formDetail','form_data','form_items','components'):
                if isinstance(detail['data'].get(kk), list):
                    raw_components = detail['data'][kk]
                    break

    # 先把每个控件 4 种名字（label / name / key / bizAlias / id）都当做 key 存，保证匹配得到
    name_to_val: Dict[str, Any] = {}
    # 特殊：钉钉自带请假控件 DDHolidayField，把请假类型+开始时间+结束时间打包在一个 value 里
    # value = '["2026-08-12 16:57","2026-08-15 16:57",16.55,"hour","事假","请假类型"]'
    dd_holiday_data: Dict[str, Any] = {}
    for comp in raw_components:
        if not isinstance(comp, dict):
            continue
        ev = comp.get('extValue') if isinstance(comp.get('extValue'), dict) else {}
        # 特殊处理 DDHolidayField（钉钉自带请假控件）
        ctype = comp.get("componentType") or comp.get("component_type") or ""
        if ctype == "DDHolidayField":
            raw_val = comp.get("value")
            try:
                arr = json.loads(raw_val) if isinstance(raw_val, str) else raw_val
                if isinstance(arr, list) and len(arr) >= 5:
                    # arr[0]=开始时间, arr[1]=结束时间, arr[2]=时长, arr[3]=单位, arr[4]=请假类型
                    dd_holiday_data = {
                        "date_start": str(arr[0])[:10] if arr[0] else "",
                        "date_end": str(arr[1])[:10] if arr[1] else "",
                        "leave_type": str(arr[4]) if arr[4] else "",
                    }
                    logger.info(f"[OA-Sync] DDHolidayField 解析: {dd_holiday_data}")
            except Exception as e:
                logger.warning(f"[OA-Sync] DDHolidayField 解析失败: {e} raw={str(raw_val)[:200]}")
            continue  # DDHolidayField 不走普通 name_to_val 匹配

        candidates = [
            comp.get("label"),
            comp.get("name"),
            comp.get("title"),
            comp.get("key"),
            comp.get("bizAlias"),
            comp.get("id"),
            comp.get("fieldId"),
            comp.get("fieldKey"),
            comp.get("componentName"),
            (isinstance(ev, dict) and (ev.get('label') or ev.get('bizAlias') or ev.get('name') or ev.get('key'))) or None,
        ]
        val = comp.get("value")
        for c in candidates:
            if not c:
                continue
            s = str(c).strip()
            if not s:
                continue
            if s not in name_to_val:  # 先出现的优先（label一般在前，最直观）
                name_to_val[s] = val

    result: Dict[str, Any] = {}
    # 优先用 DDHolidayField 解析出来的数据（如果有的话）
    if dd_holiday_data:
        result["leave_type"] = dd_holiday_data.get("leave_type", "")
        result["date_start"] = dd_holiday_data.get("date_start", "")
        result["date_end"] = dd_holiday_data.get("date_end", "")
    # 再用普通控件名匹配补充/覆盖
    for our_key, dd_key in OA_CFG.LEAVE_FIELD_MAP.items():
        if our_key in result and result[our_key]:
            continue  # DDHolidayField 已解析的不覆盖
        # 1) 直接按配置的 dd_key 匹配（优先：你在模板里设置的 bizAlias / key）
        if dd_key in name_to_val:
            result[our_key] = name_to_val[dd_key]
            continue
        # 2) 兜底：our_key 本身可能就是 label（比如 leave_type 这种场景）
        if our_key in name_to_val:
            result[our_key] = name_to_val[our_key]
    logger.info(f"[OA-Sync] 表单解析结果（our_key → value）: {json.dumps(result, ensure_ascii=False, default=str)}")
    return result


def _parse_date_range(raw_val: Any) -> Tuple[Optional[date], Optional[date]]:
    """解析时间段控件值 → (from_date, to_date)"""
    if raw_val is None:
        return None, None
    s = str(raw_val).strip()
    if not s:
        return None, None
    # 常见格式："2026-08-05 至 2026-08-07" / "2026-08-05" / "2026/08/05~2026/08/07"
    import re
    tokens = re.split(r"\s*(?:至|~|-{2,}|\|)\s*", s)
    dates: List[date] = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        # 先统一把 / 改为 -
        t_n = t.replace("/", "-").replace(".", "-")
        # 只截取前 10 个字符 "yyyy-MM-dd"
        t_n = t_n[:10]
        try:
            y, m, d = [int(x) for x in t_n.split("-")]
            dates.append(date(y, m, d))
        except Exception:
            continue
    if len(dates) >= 2:
        return dates[0], dates[-1]
    if len(dates) == 1:
        return dates[0], dates[0]
    return None, None


def _parse_shift(raw_val: Any) -> str:
    if raw_val is None:
        return LeaveShift.ALL_DAY.value
    s = str(raw_val).strip()
    if not s:
        return LeaveShift.ALL_DAY.value
    if any(k in s for k in ("上午", "早上", "早晨", "AM", "morning")):
        return LeaveShift.MORNING.value
    if any(k in s for k in ("下午", "晚上", "PM", "afternoon")):
        return LeaveShift.AFTERNOON.value
    return LeaveShift.ALL_DAY.value


def _parse_leave_type(raw_val: Any) -> str:
    """钉钉请假类型文本 → LeaveType.value"""
    if raw_val is None:
        return LeaveType.OTHER.value
    s = str(raw_val).strip()
    if not s:
        return LeaveType.OTHER.value
    if "年假" in s or "annual" in s.lower():
        return LeaveType.ANNUAL.value
    if "病假" in s or "sick" in s.lower():
        return LeaveType.SICK.value
    if "事假" in s or "personal" in s.lower():
        return LeaveType.PERSONAL.value
    if "调休" in s or "补休" in s or "compensat" in s.lower():
        return LeaveType.COMPENSATION.value
    if "婚假" in s:
        return LeaveType.MARRIAGE.value
    if "产假" in s or "生育" in s:
        return LeaveType.MATERNITY.value
    if "丧假" in s or "funeral" in s.lower():
        return LeaveType.FUNERAL.value
    return LeaveType.OTHER.value


def _parse_replacement_user(db: Session, raw_val: Any) -> Optional[User]:
    """顶岗人人员选择控件值 → 本地 User

    钉钉人员选择控件 value 常见格式：
      "userid1"
      或 JSON:  {"userid":"xxx", "name":"yyy"}
      或 List:  [{"userid":"xxx", "name":"yyy"}]
    """
    if not raw_val:
        return None
    userid_candidates: List[str] = []

    # 1. 字符串
    if isinstance(raw_val, str):
        s = raw_val.strip()
        if not s:
            return None
        # 尝试 parse JSON
        try:
            j = json.loads(s)
            raw_val = j
        except Exception:
            userid_candidates.append(s)

    # 2. 列表
    if isinstance(raw_val, list):
        for it in raw_val:
            if isinstance(it, dict):
                uid = it.get("userid") or it.get("userId") or it.get("id")
                if uid:
                    userid_candidates.append(str(uid))
            elif isinstance(it, str):
                userid_candidates.append(it)

    # 3. dict
    if isinstance(raw_val, dict):
        uid = raw_val.get("userid") or raw_val.get("userId") or raw_val.get("id")
        if uid:
            userid_candidates.append(str(uid))

    for uid in userid_candidates:
        u = db.query(User).filter(User.dingtalk_userid == uid).first()
        if u:
            return u

    # 4. 顶岗人是纯文本名字（如"王师傅"），不是 userid → 按名字模糊匹配
    for name in userid_candidates:
        # 精确匹配 real_name 或 username
        u = db.query(User).filter(
            or_(User.real_name == name, User.username == name)
        ).first()
        if u:
            logger.info(f"[OA-Sync] 顶岗人按名字匹配成功: {name} → user_id={u.id}")
            return u
        # 模糊匹配（名字包含关系）
        u = db.query(User).filter(
            or_(User.real_name.like(f"%{name}%"), User.username.like(f"%{name}%"))
        ).first()
        if u:
            logger.info(f"[OA-Sync] 顶岗人按名字模糊匹配成功: {name} → user_id={u.id}")
            return u

    logger.warning(f"[OA-Sync] 未解析到本地顶岗人用户: raw_val={raw_val}")
    return None


def _get_or_create_user_by_ddid(db: Session, ddid: str) -> Optional[User]:
    """钉钉 userid → 本地 User（找不到就尝试调钉钉接口拉详情创建）"""
    # 命中1：dingtalk_userid 直接命中（99% 场景）
    u = db.query(User).filter(User.dingtalk_userid == ddid).first()
    if u:
        return u
    # 查钉钉通讯录拉名字、手机号
    try:
        client = DingTalkClient()
        dd_detail = client.get_user_detail(ddid)
    except Exception as e:
        logger.warning(f"[OA-Sync] 拉钉钉用户详情失败 ddid={ddid}: {e}")
        dd_detail = None
    if not dd_detail:
        dd_detail = {}
    name = dd_detail.get("name") or f"钉钉用户_{ddid[-6:]}"
    phone = dd_detail.get("mobile") or ""

    # 命中2：同手机号用户已存在 → 直接绑定 dingtalk_userid
    if phone:
        same_phone = db.query(User).filter(User.phone == phone).first()
        if same_phone:
            if not same_phone.dingtalk_userid:
                same_phone.dingtalk_userid = ddid
                same_phone.dingtalk_bound_at = datetime.now()
                db.flush()
                logger.info(f"[OA-Sync] 复用已有用户 phone={phone} 绑定 dingtalk_userid={ddid}")
            return same_phone

    # 兜底：新建用户；username 直接用 dd_{ddid}，绝不复用 phone 当 username 避免冲突
    role_default = UserRole.WORKER.value if hasattr(UserRole, "WORKER") else UserRole.TECHNICIAN.value
    try:
        new_user = User(
            username=f"dd_{ddid}",
            real_name=name,
            password_hash=getattr(settings, "DEFAULT_USER_PASSWORD_HASH", "pbkdf2_sha256$200000$TODO$REPLACEME"),
            phone=phone or None,
            role=role_default,
            dingtalk_userid=ddid,
            dingtalk_bound_at=datetime.now(),
            is_active=True,
        )
        db.add(new_user)
        db.flush()
        logger.info(f"[OA-Sync] 自动创建本地用户: name={name}, ddid={ddid}, role={role_default}")
        return new_user
    except Exception as e:
        # 唯一键冲突（并发等） → 再查一次
        try:
            db.rollback()
        except Exception:
            pass
        u = db.query(User).filter(User.dingtalk_userid == ddid).first()
        if u:
            return u
        if phone:
            u = db.query(User).filter(User.phone == phone).first()
            if u:
                if not u.dingtalk_userid:
                    u.dingtalk_userid = ddid
                    u.dingtalk_bound_at = datetime.now()
                    db.flush()
                return u
        logger.exception(f"[OA-Sync] 创建/绑定用户失败 ddid={ddid}: {e}")
        return None


def _expand_date_range(d_from: date, d_to: date) -> List[date]:
    days: List[date] = []
    cur = d_from
    while cur <= d_to:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _persist_leave_request(
    db: Session,
    pi_id: str,
    detail: Dict[str, Any],
    originator_ddid: str,
    form: Dict[str, Any],
    target_status: str,
) -> Optional[LeaveRequest]:
    """DB 事务落库：主单 + 明细 + 审批通过写排班"""
    # 兼容：读取审批详情里的 result（新版是字符串/老版是dict），供本函数内部读取 remark 使用
    _result_raw = detail.get("result")

    # 1. 幂等：先查 correlation_id 是否存在
    lr = db.query(LeaveRequest).filter(LeaveRequest.correlation_id == pi_id).first()
    if lr is None:
        # 2. 申请人映射
        requester = _get_or_create_user_by_ddid(db, originator_ddid)
        if requester is None:
            logger.warning(f"[OA-Sync] 无法匹配到本地申请人 ddid={originator_ddid}，跳过审批单 {pi_id}")
            db.rollback()
            return None

        # 3. 日期：优先「开始时间 + 结束时间」两个独立控件（你截图里的模板就是这种！），
        #    兜底才用单控件「date_range 时间段」
        d_from = d_to = None
        if form.get("date_start") and form.get("date_end"):
            d_from, _ = _parse_date_range(form["date_start"])
            d_to, _ = _parse_date_range(form["date_end"])
            if not d_from or not d_to:
                logger.warning(
                    f"[OA-Sync] 拆分日期控件解析失败：date_start={form.get('date_start')}, date_end={form.get('date_end')}，"
                    f"尝试回退 date_range"
                )
        # 兜底：date_range 单控件
        if not d_from or not d_to:
            d_from, d_to = _parse_date_range(form.get("date_range"))
        if not d_from or not d_to:
            logger.warning(
                f"[OA-Sync] 无法解析请假日期：date_range={form.get('date_range')}, "
                f"date_start={form.get('date_start')}, date_end={form.get('date_end')}，跳过审批单 {pi_id}"
            )
            db.rollback()
            return None
        shift = _parse_shift(form.get("shift"))
        # 跨天非全天 → 拦截，要求全天（和 leave_requests.py 规则保持一致）
        if shift != LeaveShift.ALL_DAY.value and (d_to - d_from).days > 0:
            logger.warning(
                f"[OA-Sync] 跨天仅支持全天 (d_from={d_from}, d_to={d_to}, shift={shift})，"
                "已强制转为全天。如需按半天请提交单天申请。"
            )
            shift = LeaveShift.ALL_DAY.value
        leave_type = _parse_leave_type(form.get("leave_type"))
        note = str(form.get("note") or detail.get("remark") or "")

        # 4. 顶岗人
        replacement_user = _parse_replacement_user(db, form.get("replacement_user"))

        # 5. 创建主单
        lr = LeaveRequest(
            requester_id=requester.id,
            requester_name=requester.real_name or requester.username,
            leave_type=leave_type,
            leave_reason=note[:500] if note else "",
            status=LeaveRequestStatus.PENDING.value,
            substitute_user_id=replacement_user.id if replacement_user else None,
            correlation_id=pi_id,
            submitted_at=datetime.now(),
        )
        # LeaveRequest 表没有 date_from / date_to / shift_of_range / total_days / substitute_name 字段，
        # 这些信息用明细 details 表达，所以不在主单里写
        db.add(lr)
        db.flush()  # 拿自增 id

        # 6. 写明细 (leave_requests_details) → 注意：LeaveRequestDetail 没有 requester_id 列
        for d in _expand_date_range(d_from, d_to):
            db.add(LeaveRequestDetail(
                leave_request_id=lr.id,
                leave_date=d,
                leave_shift=shift,
            ))
        db.flush()

    # 7. 更新审批状态（即使之前是 PENDING，这里也要改成最新状态）
    was = lr.status
    lr.status = target_status
    # 审批人：取审批链最后一个（approverUserIds新版是驼峰，approvers老版），没拉到就不填
    approvers = detail.get("approverUserIds") or detail.get("approvers") or (
        isinstance(detail.get("data"), dict) and (detail["data"].get("approverUserIds") or detail["data"].get("approvers"))
    ) or []
    if isinstance(approvers, list) and approvers:
        last_approver_ddid = None
        for it in approvers:
            if isinstance(it, str):
                last_approver_ddid = it
            elif isinstance(it, dict):
                last_approver_ddid = it.get("userid") or it.get("userId")
        if last_approver_ddid:
            approver = _get_or_create_user_by_ddid(db, last_approver_ddid)
            if approver:
                lr.approver_id = approver.id
                if isinstance(_result_raw, dict):
                    lr.approver_comment = str(_result_raw.get("remark") or "") or lr.approver_comment
                elif isinstance(detail.get("result"), dict):
                    lr.approver_comment = str(detail["result"].get("remark") or "") or lr.approver_comment
    # handled_at: 审批完成时更新
    if target_status in (LeaveRequestStatus.APPROVED.value, LeaveRequestStatus.REJECTED.value, LeaveRequestStatus.CANCELLED.value):
        lr.handled_at = lr.handled_at or datetime.now()
    db.flush()
    logger.info(f"[OA-Sync] 审批单 {pi_id} 状态 {was} → {target_status}")

    # 8. 若审批通过 → 写排班（事务里做）
    if target_status == LeaveRequestStatus.APPROVED.value and was != LeaveRequestStatus.APPROVED.value:
        try:
            _apply_approved_schedules(db, lr, pi_id)
            logger.info(f"[OA-Sync] ✅ 审批通过：已同步 leave_requests({lr.id}) + duty_schedules排班")
        except Exception as e:
            logger.exception(f"[OA-Sync] 写排班失败: {e}")
            db.rollback()
            raise

    db.commit()
    db.refresh(lr)
    return lr


def _is_shift_overlap(l_shift: str, d_shift: str) -> bool:
    if l_shift == LeaveShift.ALL_DAY.value:
        return True
    return l_shift == d_shift


def _apply_approved_schedules(db: Session, lr: LeaveRequest, pi_id: str) -> None:
    """审批通过：
    1) 插入 duty_schedules = LEAVE 记录
    2) 如果有顶岗人 → 插入 duty_schedules = SUBSTITUTE 记录（顶班）
    3) 未完成工单冲突校验（有未完成工单 → 回滚，让主管先转派）
    pi_id: 用于日志追踪 correlation_id (processInstanceId)
    """
    requester_id = lr.requester_id
    sub_uid = lr.substitute_user_id
    # 用于熔断日志中“顶岗人姓名”：从 sub_uid 反查一次
    sub_user_for_log: Optional[User] = None
    if sub_uid:
        sub_user_for_log = db.query(User).filter(User.id == sub_uid).first()

    details = db.query(LeaveRequestDetail).filter(LeaveRequestDetail.leave_request_id == lr.id).all()
    pairs = [(d.leave_date, d.leave_shift) for d in details]

    # 冲突1：未完成工单（该日期的工单或指派给该申请人且未完成）
    # 用 assignee_id=requester_id 条件 + 创建日期 ld（若无派时间：created_at+派工单日期=ld）
    for ld, ls in pairs:
        q = db.query(WorkOrder).filter(
            WorkOrder.assignee_id == requester_id,
            cast(WorkOrder.created_at, SA_Date) == ld,
            WorkOrder.status.notin_([
                WorkOrderStatus.COMPLETED.value,
                WorkOrderStatus.ARCHIVED.value,
                WorkOrderStatus.REJECTED.value,
            ])
        )
        if q.first():
            raise Exception(
                f"申请人 {lr.requester_name} 在 {ld} 存在未完成工单，"
                "请假审批被拦截。请先在工单中心转派工单再审批。"
            )

    # 排班写入：先查旧的对应日期/班次 → 如果有冲突直接覆盖（LEAVE 优先）
    from app.models.duty_schedule import DutySchedule, ShiftType

    LEAVE_TYPE_VAL = "LEAVE"
    SUBSTITUTE_TYPE_VAL = "SUBSTITUTE"
    sub_uid = lr.substitute_user_id

    for ld, ls in pairs:
        shift_for_db = (
            ShiftType.MORNING.value if ls == LeaveShift.MORNING.value
            else ShiftType.AFTERNOON.value if ls == LeaveShift.AFTERNOON.value
            else ShiftType.MORNING.value  # ALL_DAY → 插两条
        )

        shifts_to_apply = [shift_for_db]
        # ALL_DAY → 同时占 MORNING + AFTERNOON 两个坑
        if ls == LeaveShift.ALL_DAY.value:
            shifts_to_apply = [ShiftType.MORNING.value, ShiftType.AFTERNOON.value]

        for s in shifts_to_apply:
            # A. 清申请人对应日期排班，并写/覆盖一条 LEAVE
            matched_rows = db.query(DutySchedule).filter(
                DutySchedule.user_id == requester_id,
                DutySchedule.date == ld,
                DutySchedule.shift == s,
            ).all()
            if matched_rows:
                for r in matched_rows:
                    r.schedule_type = LEAVE_TYPE_VAL
                    r.leave_type = lr.leave_type
                    r.leave_status = "APPROVED"
                    r.source_leave_request_id = lr.id
                    r.note = (r.note or "") + f"\n[请假审批同步] type={lr.leave_type}"
                    # 原 note 长度超了截断
                    if r.note and len(r.note) > 200:
                        r.note = r.note[:200]
                    db.flush()
            else:
                db.add(DutySchedule(
                    user_id=requester_id,
                    date=ld,
                    shift=s,
                    schedule_type=LEAVE_TYPE_VAL,
                    note=f"请假: {lr.leave_type}",
                    leave_type=lr.leave_type,
                    leave_status="APPROVED",
                    source_leave_request_id=lr.id,
                ))
                db.flush()

            # B. 顶岗人：插一条 SUBSTITUTE（顶这条请假的班）
            if sub_uid:
                exist_sub = db.query(DutySchedule).filter(
                    DutySchedule.user_id == sub_uid,
                    DutySchedule.date == ld,
                    DutySchedule.shift == s,
                ).first()
                if not exist_sub:
                    db.add(DutySchedule(
                        user_id=sub_uid,
                        date=ld,
                        shift=s,
                        schedule_type=SUBSTITUTE_TYPE_VAL,
                        note=f"替班: {lr.requester_name}",
                        source_leave_request_id=lr.id,
                        source_substitute_for_id=lr.id,
                    ))
                    db.flush()

    # 熔断校验：钉钉 OA 审批同步，主管已经在钉钉里点了同意，
    # 这里只做"检查 + 打告警"，不强制回滚（避免同步失败导致排班不一致）。
    # 人数不足时，用 WARNING 日志提醒，让主管事后人工处理（增加临时排班 / 再派一个顶岗人）。
    try:
        min_guard = int(sys_conf.get(db, "min_guard_count", "2"))
    except TypeError:
        min_guard = int(sys_conf.get("min_guard_count", "2", db=db))  # type: ignore[call-arg]
    for ld, ls in pairs:
        shifts_to_check = (
            [ShiftType.MORNING.value, ShiftType.AFTERNOON.value]
            if ls == LeaveShift.ALL_DAY.value
            else [(
                ShiftType.MORNING.value if ls == LeaveShift.MORNING.value
                else ShiftType.AFTERNOON.value
            )]
        )
        for s in shifts_to_check:
            all_rows = db.query(DutySchedule).filter(
                DutySchedule.date == ld, DutySchedule.shift == s,
            ).all()
            working = {
                r.user_id for r in all_rows
                if r.schedule_type not in (LEAVE_TYPE_VAL,) and r.leave_status != "APPROVED"
            }
            if len(working) < min_guard:
                if not sub_uid:
                    logger.warning(
                        f"[OA-Sync] ⚠️ 审批通过但未指定顶岗人：{ld} {s} 在岗 {len(working)} 人 < 最低 {min_guard} 人。"
                        f"请主管手动补排班或在后续审批单里指定顶岗人。（请假单 pid={pi_id}）"
                    )
                    continue
                sub_rows = db.query(DutySchedule).filter(
                    DutySchedule.user_id == sub_uid,
                    DutySchedule.date == ld,
                    DutySchedule.shift == s,
                ).all()
                if any(r.schedule_type == LEAVE_TYPE_VAL for r in sub_rows):
                    sub_user = sub_user_for_log
                    if sub_user is None:
                        sub_user = db.query(User).filter(User.id == sub_uid).first()
                    sub_name = (
                        (sub_user.real_name or sub_user.username)
                        if sub_user else f"uid={sub_uid}"
                    )
                    logger.warning(
                        f"[OA-Sync] ⚠️ 指定的顶岗人 {sub_name} 在 {ld} {s} 自身也处于请假状态，"
                        f"无法顶岗。请主管人工处理（请假单 pid={pi_id}）"
                    )
