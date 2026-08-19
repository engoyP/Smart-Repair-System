"""请假申请单 API (Phase 2.1 Day2)

接口清单：
  POST   /                  提交请假申请（师傅端 / 钉钉卡片回调）
  GET    /                  查询请假列表（支持按状态/人员/日期过滤）
  GET    /{id}              请假详情
  POST   /{id}/approve      主管批准（含工单冲突校验、人数熔断顶岗、写入排班事务）
  POST   /{id}/reject       主管拒绝
  POST   /{id}/cancel       师傅撤销（仅 PENDING 状态）
  GET    /my                当前登录用户的请假记录
  GET    /check-conflicts   预检：提交前先查未完成工单冲突 + 人数不足警告
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, cast
from sqlalchemy.types import Date as SA_Date
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta
from pydantic import BaseModel, Field
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.core import sys_config as sys_conf
from app.models.user import User, UserRole
from app.models.leave_request import (
    LeaveRequest, LeaveRequestDetail,
    LeaveType, LeaveRequestStatus, LeaveShift,
)
from app.models.duty_schedule import DutySchedule, ShiftType
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.schemas import (
    LeaveRequestSubmit, LeaveRequestApprove, LeaveRequestReject,
    LeaveRequestResponse, LeaveRequestDetailResponse,
    PaginatedResponse,
)

router = APIRouter()


# ============================================================
# 内部工具函数
# ============================================================

def _expand_date_range(d_from: date, d_to: date) -> List[date]:
    """展开日期区间 [d_from, d_to] → 日期列表"""
    if d_from > d_to:
        raise HTTPException(status_code=422, detail="date_from 不能晚于 date_to")
    days: List[date] = []
    cur = d_from
    while cur <= d_to:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _parse_details_from_submit(payload: LeaveRequestSubmit) -> List[tuple]:
    """解析 LeaveRequestSubmit → [(leave_date, leave_shift), ...] 去重列表"""
    pairs: List[tuple] = []
    seen = set()
    if payload.details and len(payload.details) > 0:
        for d in payload.details:
            key = (d.leave_date, d.leave_shift or LeaveShift.ALL_DAY.value)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
    elif payload.date_from and payload.date_to:
        # 跨天非全天 → 拦截（师傅端应该提示只能全天跨天）
        shift = payload.shift_of_range or LeaveShift.ALL_DAY.value
        if shift != LeaveShift.ALL_DAY.value and (payload.date_to - payload.date_from).days > 0:
            raise HTTPException(status_code=422, detail="跨天请假仅支持全天班次，如分时段请逐条填写")
        for d in _expand_date_range(payload.date_from, payload.date_to):
            key = (d, shift)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
    else:
        raise HTTPException(status_code=422, detail="请提供日期区间 date_from+date_to，或显式明细 details")
    if not pairs:
        raise HTTPException(status_code=422, detail="未解析到任何请假明细，请检查日期")
    return pairs


def _validate_leave_type(t: str) -> str:
    allowed = {e.value for e in LeaveType}
    if t not in allowed:
        raise HTTPException(status_code=422, detail=f"leave_type 不合法，允许值: {sorted(allowed)}")
    return t


def _validate_shift(s: str) -> str:
    allowed = {e.value for e in LeaveShift} | {e.value for e in ShiftType}
    if s not in allowed:
        raise HTTPException(status_code=422, detail=f"leave_shift 不合法，允许值: {sorted(allowed)}")
    return s


def _is_leave_shift_overlap_shift(leave_shift: str, duty_shift: str) -> bool:
    """判断「请假班次」与「排班班次」是否有时间交叠。
    ALL_DAY ↔ 任何班次都算交叠；其余按字符串相等判断。
    """
    if leave_shift == LeaveShift.ALL_DAY.value:
        return True
    return leave_shift == duty_shift


def _build_response(lr: LeaveRequest) -> Dict[str, Any]:
    """ORM → response dict"""
    return {
        "id": lr.id,
        "requester_id": lr.requester_id,
        "requester_name": lr.requester_name,
        "leave_type": lr.leave_type,
        "leave_reason": lr.leave_reason,
        "status": lr.status,
        "approver_id": lr.approver_id,
        "approver_comment": lr.approver_comment,
        "substitute_user_id": lr.substitute_user_id,
        "correlation_id": lr.correlation_id,
        "submitted_at": lr.submitted_at,
        "handled_at": lr.handled_at,
        "details": [
            {
                "id": d.id,
                "leave_request_id": d.leave_request_id,
                "leave_date": d.leave_date,
                "leave_shift": d.leave_shift,
            }
            for d in (lr.details or [])
        ],
        "created_at": lr.created_at,
        "updated_at": lr.updated_at,
        "on_duty_after": None,
        "pending_work_orders": None,
    }


def _require_supervisor_or_admin(current_user: User):
    if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail="仅主管/管理员可执行此操作")


# ============================================================
# 预检接口（前端/钉钉卡片提交前调用，辅助展示冲突与警告）
# ============================================================
class PreCheckResponse(BaseModel):
    pending_work_orders: List[Dict[str, Any]] = []
    daily_on_duty_after: Dict[str, int] = {}
    min_guard_count: int = 2
    need_substitute: bool = False
    need_substitute_on_dates: List[str] = []


@router.get("/check-conflicts", response_model=PreCheckResponse, summary="预检：工单冲突 + 人数不足警告")
def check_leave_conflicts(
    requester_id: int = Query(..., description="请假师傅 user_id"),
    date_from: Optional[date] = Query(None, description="日期区间起"),
    date_to: Optional[date] = Query(None, description="日期区间止"),
    shift: Optional[str] = Query("ALL_DAY", description="区间统一班次；不传明细时生效"),
    details: Optional[str] = Query(None, description='明细 JSON: [{"leave_date":"2026-08-05","leave_shift":"MORNING"}]'),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """师傅端提交请假前先调一次，把冲突工单 + 每天剩余值班人数 + 是否需要强制顶岗返回前端渲染"""
    # 解析目标 (date, shift) pairs
    import json as _json
    pairs: List[tuple] = []
    if details:
        try:
            arr = _json.loads(details)
            for d in arr:
                pairs.append((date.fromisoformat(d["leave_date"]), d.get("leave_shift") or LeaveShift.ALL_DAY.value))
        except Exception:
            raise HTTPException(status_code=422, detail="details JSON 格式不正确")
    elif date_from and date_to:
        shift_val = shift or LeaveShift.ALL_DAY.value
        if shift_val != LeaveShift.ALL_DAY.value and (date_to - date_from).days > 0:
            raise HTTPException(status_code=422, detail="跨天请假仅支持全天班次")
        for d in _expand_date_range(date_from, date_to):
            pairs.append((d, shift_val))
    else:
        raise HTTPException(status_code=422, detail="请传 date_from+date_to 或 details")
    pairs = list({p: 1 for p in pairs}.keys())

    # 1) 未完成工单：technician_id=该师傅，状态非 COMPLETED/REJECTED/DRAFT
    terminal = {WorkOrderStatus.COMPLETED.value, WorkOrderStatus.REJECTED.value, WorkOrderStatus.DRAFT.value,
                "ARCHIVED"}
    leave_dates = sorted({p[0] for p in pairs})
    d_min, d_max = leave_dates[0], leave_dates[-1]
    wo_q = db.query(WorkOrder).filter(
        WorkOrder.technician_id == requester_id,
        WorkOrder.status.notin_(list(terminal)),
    ).all()
    pending_wo: List[Dict[str, Any]] = []
    for w in wo_q:
        wo_created_date = cast(w.created_at, SA_Date) if w.created_at else None
        # 近似判断：created_at 在请假区间里，或 start_time 交叠
        overlap = False
        if w.start_time:
            s = w.start_time.date()
            overlap = (d_min <= s <= d_max)
        elif wo_created_date is not None:
            # 无 start_time 则认为在创建日期之后几天都算未完成
            overlap = (d_min <= wo_created_date <= d_max) or (wo_created_date < d_min)
        if overlap:
            pending_wo.append({
                "work_order_id": w.id,
                "work_order_no": w.work_order_no,
                "status": w.status,
                "fault_description": w.fault_description,
                "start_time": w.start_time.isoformat() if w.start_time else None,
            })

    # 2) 每天剩余值班人数 = (当天总排班数 - 请假交叠班次条数），仅统计已排班师傅（MANUAL/WEEKLY_ROUTINE/未删除）
    min_guard = sys_conf.get(db, "min_guard_count", 2)
    duty_type_ok = {t.value for t in ["MANUAL", "WEEKLY_ROUTINE"]} if False else {"MANUAL", "WEEKLY_ROUTINE", "SUBSTITUTE"}
    daily_on_duty: Dict[str, int] = {}
    need_dates: List[str] = []
    for (ld, ls) in pairs:
        # 当天所有正常排班（排除 LEAVE 类型）
        duties = db.query(DutySchedule).filter(
            DutySchedule.date == ld,
            DutySchedule.schedule_type.in_(list(duty_type_ok)),
        ).all()
        # 减去本次请假交叠掉的 unique user
        overlap_users = set()
        for du in duties:
            if du.user_id == requester_id and _is_leave_shift_overlap_shift(ls, du.shift):
                overlap_users.add(du.user_id)
        remaining = len({d.user_id for d in duties}) - len(overlap_users)
        # 如果是半天请假，且请假者当天另一班次仍在值班 → 不单独扣
        # 简化：先按 date 聚合
        key = ld.isoformat()
        daily_on_duty.setdefault(key, 9999)
        daily_on_duty[key] = min(daily_on_duty[key], remaining)
    for k, v in daily_on_duty.items():
        if v < min_guard:
            need_dates.append(k)
    return PreCheckResponse(
        pending_work_orders=pending_wo,
        daily_on_duty_after=daily_on_duty,
        min_guard_count=min_guard,
        need_substitute=len(need_dates) > 0,
        need_substitute_on_dates=need_dates,
    )


# ============================================================
# 提交请假申请
# ============================================================
@router.post("/", response_model=LeaveRequestResponse, summary="提交请假申请")
def submit_leave_request(
    payload: LeaveRequestSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1) correlation_id 幂等：已存在则直接返回（不报错，保证钉钉重试安全）
    exist = db.query(LeaveRequest).filter(LeaveRequest.correlation_id == payload.correlation_id).first()
    if exist:
        logger.info(f"[Leave] correlation_id 命中幂等: {payload.correlation_id} -> lr_id={exist.id}")
        return _build_response(exist)

    # 2) 确定申请人
    requester_id = payload.requester_id or current_user.id
    requester = db.query(User).filter(User.id == requester_id).first()
    if not requester:
        raise HTTPException(status_code=404, detail="申请人不存在")

    # 3) 解析 pairs 并校验
    pairs = _parse_details_from_submit(payload)
    leave_type = _validate_leave_type(payload.leave_type)

    # 4) 落库主表 + 明细
    lr = LeaveRequest(
        requester_id=requester_id,
        requester_name=requester.real_name or requester.username,
        leave_type=leave_type,
        leave_reason=payload.leave_reason,
        status=LeaveRequestStatus.PENDING.value,
        correlation_id=payload.correlation_id,
        submitted_at=datetime.utcnow(),
    )
    db.add(lr)
    db.flush()  # 拿到 lr.id
    for (ld, ls) in pairs:
        _validate_shift(ls)
        db.add(LeaveRequestDetail(
            leave_request_id=lr.id,
            leave_date=ld,
            leave_shift=ls,
        ))
    db.commit()
    db.refresh(lr)
    logger.info(f"[Leave] 提交成功 lr_id={lr.id} requester={requester_id} 明细数={len(pairs)}")
    return _build_response(lr)


# ============================================================
# 查询列表 / 详情 / 我的
# ============================================================
@router.get("/", response_model=PaginatedResponse[LeaveRequestResponse], summary="请假列表（主管/管理员用）")
def list_leave_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: Optional[str] = Query(None, description="PENDING/APPROVED/REJECTED/CANCELLED"),
    requester_id: Optional[int] = Query(None),
    approver_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None, description="与请假明细日期交叠起始"),
    date_to: Optional[date] = Query(None, description="与请假明细日期交叠截止"),
    leave_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_supervisor_or_admin(current_user)
    q = db.query(LeaveRequest)
    if status:
        q = q.filter(LeaveRequest.status == status)
    if requester_id:
        q = q.filter(LeaveRequest.requester_id == requester_id)
    if approver_id:
        q = q.filter(LeaveRequest.approver_id == approver_id)
    if leave_type:
        q = q.filter(LeaveRequest.leave_type == leave_type)
    if date_from or date_to:
        # 子查询：关联明细交叠
        sub = db.query(LeaveRequestDetail.leave_request_id)
        if date_from:
            sub = sub.filter(LeaveRequestDetail.leave_date >= date_from)
        if date_to:
            sub = sub.filter(LeaveRequestDetail.leave_date <= date_to)
        q = q.filter(LeaveRequest.id.in_(sub))
    total = q.count()
    items = q.order_by(LeaveRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "items": [_build_response(x) for x in items],
        "page": page,
        "page_size": page_size,
    }


@router.get("/my", response_model=PaginatedResponse[LeaveRequestResponse], summary="当前用户的请假记录")
def my_leave_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(LeaveRequest).filter(LeaveRequest.requester_id == current_user.id)
    if status:
        q = q.filter(LeaveRequest.status == status)
    total = q.count()
    items = q.order_by(LeaveRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_build_response(x) for x in items], "page": page, "page_size": page_size}


@router.get("/{lr_id}", response_model=LeaveRequestResponse, summary="请假详情")
def get_leave_request(
    lr_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lr = db.query(LeaveRequest).filter(LeaveRequest.id == lr_id).first()
    if not lr:
        raise HTTPException(status_code=404, detail="请假申请不存在")
    # 权限：申请人自己、或主管/管理员
    if lr.requester_id != current_user.id:
        _require_supervisor_or_admin(current_user)
    resp = _build_response(lr)
    # 详情里带冲突工单 + 值班人数（前端审批页渲染）
    try:
        pc = check_leave_conflicts(
            requester_id=lr.requester_id,
            date_from=None, date_to=None, shift=None,
            details=_details_to_json(lr.details),
            db=db, current_user=current_user,
        )
        resp["pending_work_orders"] = pc.pending_work_orders
        resp["on_duty_after"] = pc.daily_on_duty_after
    except Exception as e:
        logger.debug(f"[Leave] 预检附加信息失败: {e}")
    return resp


def _details_to_json(details) -> str:
    import json
    return json.dumps([{"leave_date": d.leave_date.isoformat(), "leave_shift": d.leave_shift} for d in details],
                      ensure_ascii=False)


# ============================================================
# 主管批准（核心事务）
# ============================================================
@router.post("/{lr_id}/approve", response_model=LeaveRequestResponse, summary="主管批准请假申请")
def approve_leave_request(
    lr_id: int,
    payload: LeaveRequestApprove,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_supervisor_or_admin(current_user)
    lr: Optional[LeaveRequest] = db.query(LeaveRequest).filter(LeaveRequest.id == lr_id).first()
    if not lr:
        raise HTTPException(status_code=404, detail="请假申请不存在")
    if lr.status != LeaveRequestStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"当前状态 {lr.status} 不可批准，仅 PENDING 可操作")

    details: List[LeaveRequestDetail] = list(lr.details or [])
    if not details:
        raise HTTPException(status_code=409, detail="请假明细为空，无法审批")

    # ------------------------------------------------------------------
    # 1) 工单前置校验：有未完成且与请假日期交叠的工单 → 回滚拦截
    # ------------------------------------------------------------------
    terminal_statuses = {WorkOrderStatus.COMPLETED.value, WorkOrderStatus.REJECTED.value,
                         WorkOrderStatus.DRAFT.value, "ARCHIVED"}
    leave_dates = sorted({d.leave_date for d in details})
    d_min, d_max = leave_dates[0], leave_dates[-1]
    pending_wos = db.query(WorkOrder).filter(
        WorkOrder.technician_id == lr.requester_id,
        WorkOrder.status.notin_(list(terminal_statuses)),
    ).all()
    conflict_wos = []
    for w in pending_wos:
        w_date = None
        if w.start_time:
            w_date = w.start_time.date()
        elif w.created_at:
            w_date = w.created_at.date()
        if w_date and (d_min <= w_date <= d_max):
            conflict_wos.append(w)
        elif not w_date:
            conflict_wos.append(w)
    if conflict_wos:
        msg = "该师傅在请假日期内有未完成工单，请先转派工单再审批：" + "、".join(
            f"#{w.work_order_no}" for w in conflict_wos
        )
        raise HTTPException(status_code=409, detail=msg)

    # ------------------------------------------------------------------
    # 2) 人数熔断：计算请假后每天在岗人数；有任一天 < min_guard_count，必须传 substitute_user_id
    # ------------------------------------------------------------------
    min_guard = sys_conf.get(db, "min_guard_count", 2)
    duty_type_ok = {"MANUAL", "WEEKLY_ROUTINE", "SUBSTITUTE"}
    date_remaining: Dict[date, int] = {}
    for dt in details:
        duties = db.query(DutySchedule).filter(
            DutySchedule.date == dt.leave_date,
            DutySchedule.schedule_type.in_(list(duty_type_ok)),
        ).all()
        overlap_users = set()
        for du in duties:
            if du.user_id == lr.requester_id and _is_leave_shift_overlap_shift(dt.leave_shift, du.shift):
                overlap_users.add(du.user_id)
        remaining = len({d.user_id for d in duties}) - len(overlap_users)
        # 聚合 (半天不重复扣)
        prev = date_remaining.get(dt.leave_date, 9999)
        date_remaining[dt.leave_date] = min(prev, remaining)
    any_understaffed = any(v < min_guard for v in date_remaining.values())
    if any_understaffed and not payload.substitute_user_id:
        raise HTTPException(status_code=409,
                            detail=f"在岗人数低于最低值班人数({min_guard})，请指定顶岗人 substitute_user_id")

    # ------------------------------------------------------------------
    # 3) 事务性写入：更新主表状态 + 写入 LEAVE 排班 + (可选) 写入 SUBSTITUTE 顶岗排班
    # ------------------------------------------------------------------
    try:
        now = datetime.utcnow()
        lr.status = LeaveRequestStatus.APPROVED.value
        lr.approver_id = current_user.id
        lr.approver_comment = payload.approver_comment
        lr.substitute_user_id = payload.substitute_user_id
        lr.handled_at = now

        # 3a. 为每条 detail 插入 LEAVE 类型排班（若该师傅当天该班次已有 MANUAL/ROUTINE 排班，则先把它变为 LEAVE 或追加一条 LEAVE；
        #      这里采用：查找当日该师傅该班次的排班记录 → 若存在就改 schedule_type=LEAVE + 关联字段；否则插入一条）
        for dt in details:
            if dt.leave_shift == LeaveShift.ALL_DAY.value:
                target_shifts = [ShiftType.MORNING.value, ShiftType.AFTERNOON.value, ShiftType.NIGHT.value]
            else:
                target_shifts = [dt.leave_shift]
            for sh in target_shifts:
                existing = db.query(DutySchedule).filter(
                    DutySchedule.date == dt.leave_date,
                    DutySchedule.shift == sh,
                    DutySchedule.user_id == lr.requester_id,
                ).first()
                if existing:
                    existing.schedule_type = "LEAVE"
                    existing.leave_type = lr.leave_type
                    existing.leave_status = LeaveRequestStatus.APPROVED.value
                    existing.source_leave_request_id = lr.id
                    existing.note = f"请假审批{lr.id}自动同步" or existing.note
                else:
                    db.add(DutySchedule(
                        date=dt.leave_date,
                        shift=sh,
                        user_id=lr.requester_id,
                        schedule_type="LEAVE",
                        note=f"请假审批{lr.id}自动生成",
                        leave_type=lr.leave_type,
                        leave_status=LeaveRequestStatus.APPROVED.value,
                        source_leave_request_id=lr.id,
                    ))

        # 3b. 如果指定了 substitute_user_id → 在相同 (date, shift) 上插入 SUBSTITUTE 排班（不要重复插入同一天同一人同一班次）
        if payload.substitute_user_id:
            sub_user = db.query(User).filter(User.id == payload.substitute_user_id).first()
            if not sub_user:
                raise HTTPException(status_code=404, detail="顶岗人不存在")
            for dt in details:
                if dt.leave_shift == LeaveShift.ALL_DAY.value:
                    target_shifts = [ShiftType.MORNING.value, ShiftType.AFTERNOON.value, ShiftType.NIGHT.value]
                else:
                    target_shifts = [dt.leave_shift]
                for sh in target_shifts:
                    dup = db.query(DutySchedule).filter(
                        DutySchedule.date == dt.leave_date,
                        DutySchedule.shift == sh,
                        DutySchedule.user_id == payload.substitute_user_id,
                        DutySchedule.schedule_type == "SUBSTITUTE",
                        DutySchedule.source_substitute_for_id == lr.id,
                    ).first()
                    if dup:
                        continue
                    # 如该顶岗人当天该班次已经有正常排班，也允许叠加（SUBSTITUTE 是额外的值班状态），可重复
                    db.add(DutySchedule(
                        date=dt.leave_date,
                        shift=sh,
                        user_id=payload.substitute_user_id,
                        schedule_type="SUBSTITUTE",
                        note=f"顶替 {lr.requester_name} 请假#{lr.id}",
                        leave_status=LeaveRequestStatus.APPROVED.value,
                        source_substitute_for_id=lr.id,
                    ))

        db.commit()
        db.refresh(lr)
        logger.info(
            f"[Leave] 批准成功 lr_id={lr.id} 审批人={current_user.id} "
            f"顶岗={payload.substitute_user_id} 明细={len(details)}"
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"[Leave] 批准事务失败: {e}")
        raise HTTPException(status_code=500, detail=f"审批事务失败: {e}")

    return _build_response(lr)


# ============================================================
# 主管拒绝
# ============================================================
@router.post("/{lr_id}/reject", response_model=LeaveRequestResponse, summary="主管拒绝请假申请")
def reject_leave_request(
    lr_id: int,
    payload: LeaveRequestReject,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_supervisor_or_admin(current_user)
    lr = db.query(LeaveRequest).filter(LeaveRequest.id == lr_id).first()
    if not lr:
        raise HTTPException(status_code=404, detail="请假申请不存在")
    if lr.status != LeaveRequestStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"当前状态 {lr.status} 不可拒绝，仅 PENDING 可操作")
    lr.status = LeaveRequestStatus.REJECTED.value
    lr.approver_id = current_user.id
    lr.approver_comment = payload.approver_comment
    lr.handled_at = datetime.utcnow()
    db.commit()
    db.refresh(lr)
    logger.info(f"[Leave] 拒绝成功 lr_id={lr.id} 审批人={current_user.id}")
    return _build_response(lr)


# ============================================================
# 师傅撤销（仅 PENDING）
# ============================================================
@router.post("/{lr_id}/cancel", response_model=LeaveRequestResponse, summary="师傅撤销请假申请（仅本人PENDING可）")
def cancel_leave_request(
    lr_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lr = db.query(LeaveRequest).filter(LeaveRequest.id == lr_id).first()
    if not lr:
        raise HTTPException(status_code=404, detail="请假申请不存在")
    if lr.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅申请人本人可撤销")
    if lr.status != LeaveRequestStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"当前状态 {lr.status} 不可撤销，仅 PENDING 可操作")
    lr.status = LeaveRequestStatus.CANCELLED.value
    lr.handled_at = datetime.utcnow()
    db.commit()
    db.refresh(lr)
    logger.info(f"[Leave] 撤销成功 lr_id={lr.id} 申请人={current_user.id}")
    return _build_response(lr)
