from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import date, datetime, timedelta
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.duty_schedule import DutySchedule, ShiftType

router = APIRouter()


class DutyScheduleItem(BaseModel):
    shift: ShiftType
    user_ids: List[int]
    schedule_type: str = "MANUAL"
    note: Optional[str] = None


class DutyBatchCreate(BaseModel):
    date_from: date
    date_to: date
    items: List[DutyScheduleItem]


class DutyScheduleUpdate(BaseModel):
    shift: Optional[ShiftType] = None
    note: Optional[str] = None
    schedule_type: Optional[str] = None
    user_id: Optional[int] = None


class DutyScheduleResponse(BaseModel):
    id: int
    date: date
    shift: str
    user_id: int
    user_name: str
    schedule_type: str
    note: Optional[str]
    leave_type: Optional[str]
    leave_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DutyTodayResponse(BaseModel):
    MORNING: List[DutyScheduleResponse] = []
    AFTERNOON: List[DutyScheduleResponse] = []
    NIGHT: List[DutyScheduleResponse] = []


def _to_response(ds: DutySchedule) -> dict:
    return {
        "id": ds.id,
        "date": ds.date,
        "shift": ds.shift,
        "user_id": ds.user_id,
        "user_name": ds.user.real_name if ds.user else "",
        "schedule_type": ds.schedule_type,
        "note": ds.note,
        "leave_type": ds.leave_type,
        "leave_status": ds.leave_status,
        "created_at": ds.created_at,
    }


def _require_supervisor_or_admin(current_user: User):
    if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail="仅主管或管理员可执行此操作")


def _require_manage_role(current_user: User):
    if current_user.role not in ('ADMIN', 'SUPERVISOR', 'MANAGER', UserRole.ADMIN.value, UserRole.SUPERVISOR.value):
        raise HTTPException(status_code=403, detail="仅管理员/主管/经理可执行此操作")


def _get_shift_by_hour(hour: int) -> str:
    if 8 <= hour < 12:
        return "MORNING"
    elif 12 <= hour < 18:
        return "AFTERNOON"
    elif (18 <= hour < 24) or (0 <= hour < 8):
        return "NIGHT"
    return "MORNING"


class LeaveBatchCreate(BaseModel):
    user_ids: List[int]
    start_date: date
    end_date: date
    leave_type: str
    shift: str = "ALL_DAY"
    note: Optional[str] = None


class BatchDeleteRequest(BaseModel):
    ids: List[int]


class CopyWeekRequest(BaseModel):
    source_start_date: date
    target_start_date: date


@router.get("/", response_model=List[DutyScheduleResponse], summary="查询排班列表（单日或日期范围）")
def list_duty_schedules(
    date: Optional[date] = Query(None, description="单日查询 YYYY-MM-DD"),
    date_from: Optional[date] = Query(None, alias="from", description="范围查询起始（含）"),
    date_to: Optional[date] = Query(None, alias="to", description="范围查询结束（含）"),
    shift: Optional[ShiftType] = Query(None, description="可选：班次过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if date is None and (date_from is None or date_to is None):
        raise HTTPException(status_code=422, detail="请提供 date（单日）或 from+to（日期范围）参数")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="from 不能晚于 to")
    if date is not None:
        query = db.query(DutySchedule).filter(DutySchedule.date == date)
    else:
        query = db.query(DutySchedule).filter(DutySchedule.date >= date_from, DutySchedule.date <= date_to)
    if shift:
        query = query.filter(DutySchedule.shift == shift.value)
    if date is not None:
        items = query.order_by(DutySchedule.shift, DutySchedule.id).all()
    else:
        items = query.order_by(DutySchedule.date.desc(), DutySchedule.shift, DutySchedule.id).all()
    return [_to_response(ds) for ds in items]


@router.get("/today", response_model=DutyTodayResponse, summary="获取今日排班（分组）")
def get_today_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = datetime.now().date()
    items = (
        db.query(DutySchedule)
        .filter(DutySchedule.date == today)
        .order_by(DutySchedule.shift, DutySchedule.id)
        .all()
    )
    result = {"MORNING": [], "AFTERNOON": [], "NIGHT": []}
    for ds in items:
        shift_key = ds.shift
        if shift_key in result:
            result[shift_key].append(_to_response(ds))
    return result


@router.get("/week", summary="查询一周排班矩阵（按人聚合）")
def get_week_schedules(
    start_date: date = Query(..., description="周起始日期 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    end_date = start_date + timedelta(days=6)

    # 查询该范围内所有排班记录
    schedules = (
        db.query(DutySchedule)
        .filter(DutySchedule.date >= start_date, DutySchedule.date <= end_date)
        .all()
    )

    # 查询所有活跃的维修员
    tech_roles = ('technician', 'repairer', 'engineer',
                  'TECHNICIAN', 'REPAIRER', 'ENGINEER',
                  UserRole.TECHNICIAN.value)
    active_techs = (
        db.query(User)
        .filter(User.role.in_(tech_roles), User.is_active == True)
        .order_by(User.id)
        .all()
    )

    # 按 (user_id, date) 聚合排班记录
    user_day_map = {}  # user_id -> {date_str -> {"leaves": [], "shifts": []}}
    for s in schedules:
        date_str = s.date.isoformat()
        day_data = (
            user_day_map.setdefault(s.user_id, {})
            .setdefault(date_str, {"leaves": [], "shifts": []})
        )
        if s.schedule_type == 'LEAVE':
            day_data["leaves"].append(s)
        else:
            day_data["shifts"].append(s)

    # 组装 7 天的视图
    date_list = [start_date + timedelta(days=i) for i in range(7)]
    users_result = []
    for u in active_techs:
        days = {}
        user_days = user_day_map.get(u.id, {})
        for d in date_list:
            date_str = d.isoformat()
            day_data = user_days.get(date_str)
            if not day_data or (not day_data["leaves"] and not day_data["shifts"]):
                # 无记录的天返回空值
                days[date_str] = {"shifts": [], "shift": None, "schedule_type": None, "leave_info": None}
                continue

            leaves = day_data["leaves"]
            shifts = day_data["shifts"]

            # leave_info 来自请假记录
            leave_info = None
            if leaves:
                lv = leaves[0]
                leave_info = {"leave_type": lv.leave_type, "shift": lv.shift}

            if shifts:
                # 多个班次并列展示：shifts 数组（含 id）供前端渲染/删除，shift 字符串保留兼容
                days[date_str] = {
                    "shifts": [
                        {"id": s.id, "shift": s.shift, "schedule_type": s.schedule_type}
                        for s in shifts
                    ],
                    "shift": ",".join(sorted({s.shift for s in shifts})),
                    "schedule_type": shifts[0].schedule_type,
                    "leave_info": leave_info,
                }
            else:
                # 仅有请假记录
                days[date_str] = {
                    "shifts": [],
                    "shift": None,
                    "schedule_type": "LEAVE",
                    "leave_info": leave_info,
                }

        users_result.append({
            "user_id": u.id,
            "real_name": u.real_name,
            "employee_id": u.employee_id,
            "days": days,
        })

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "users": users_result,
    }


@router.post("/", summary="批量创建排班")
def batch_create_duty_schedules(
    data: DutyBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_supervisor_or_admin(current_user)

    if data.date_from > data.date_to:
        raise HTTPException(status_code=400, detail="date_from 不能晚于 date_to")

    date_range = []
    cur = data.date_from
    while cur <= data.date_to:
        date_range.append(cur)
        cur += timedelta(days=1)

    # 预加载本次涉及的所有用户
    all_user_ids = set()
    for item in data.items:
        for uid in item.user_ids:
            all_user_ids.add(uid)
    users = db.query(User).filter(User.id.in_(all_user_ids)).all() if all_user_ids else []
    user_map = {u.id: u for u in users}

    # 收集冲突项与待创建记录
    conflicts = []
    to_create = []
    skipped_count = 0
    pending_keys = set()  # 本次批次中已排队创建的 (date, shift, user_id)

    for d in date_range:
        for item in data.items:
            shift_val = item.shift.value
            for user_id in item.user_ids:
                user = user_map.get(user_id)
                user_name = user.real_name if user else f"user_id={user_id}"

                # 查询该用户当天的所有排班记录
                existing_records = (
                    db.query(DutySchedule)
                    .filter(
                        DutySchedule.date == d,
                        DutySchedule.user_id == user_id,
                    )
                    .all()
                )

                # 冲突校验1：全天请假 → 强制冲突
                has_all_day_leave = any(
                    r.schedule_type == 'LEAVE' and r.shift == 'ALL_DAY'
                    for r in existing_records
                )
                if has_all_day_leave:
                    conflicts.append({
                        "user_id": user_id,
                        "user_name": user_name,
                        "date": d.isoformat(),
                        "reason": f"排班冲突：{user_name} 在 {d.isoformat()} 全天请假",
                    })
                    continue

                # 用户不存在 → 跳过
                if not user:
                    logger.warning(f"[DutySchedule] 用户不存在，跳过: user_id={user_id}")
                    skipped_count += 1
                    continue

                # 相同 shift 已存在 → 跳过（保持现有逻辑）
                # 不同 shift（非请假）→ 允许；半天请假 + 不同时段 → 允许
                key = (d, shift_val, user_id)
                has_same_shift = any(r.shift == shift_val for r in existing_records)
                if has_same_shift or key in pending_keys:
                    skipped_count += 1
                    continue

                to_create.append({
                    "date": d,
                    "shift": shift_val,
                    "user_id": user_id,
                    "schedule_type": item.schedule_type or "MANUAL",
                    "note": item.note,
                })
                pending_keys.add(key)

    # 存在冲突则全部不创建，返回冲突详情
    if conflicts:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "排班冲突，未创建任何记录",
                "conflicts": conflicts,
            },
        )

    # 执行创建
    created_count = 0
    for item in to_create:
        ds = DutySchedule(
            date=item["date"],
            shift=item["shift"],
            user_id=item["user_id"],
            schedule_type=item["schedule_type"],
            note=item["note"],
        )
        db.add(ds)
        created_count += 1

    db.commit()
    logger.info(
        f"[DutySchedule] 批量创建完成: created={created_count}, skipped={skipped_count}, "
        f"date_range=[{data.date_from} ~ {data.date_to}], operator={current_user.id}"
    )
    return {
        "message": "批量排班完成",
        "created": created_count,
        "skipped": skipped_count,
        "date_count": len(date_range),
    }


@router.post("/copy-week", summary="复制上周排班到本周")
def copy_week_schedules(
    data: CopyWeekRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_supervisor_or_admin(current_user)

    source_start = data.source_start_date
    source_end = source_start + timedelta(days=6)

    # 查询源周排班记录（排除 LEAVE 类型）
    source_schedules = (
        db.query(DutySchedule)
        .filter(
            DutySchedule.date >= source_start,
            DutySchedule.date <= source_end,
            DutySchedule.schedule_type != 'LEAVE',
        )
        .all()
    )

    # 预加载用户名映射
    user_ids = {s.user_id for s in source_schedules}
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    user_name_map = {u.id: u.real_name for u in users}

    created_count = 0
    skipped = []

    for s in source_schedules:
        # 映射到目标周的对应日期（+7天偏移）
        offset_days = (s.date - source_start).days
        target_date = data.target_start_date + timedelta(days=offset_days)

        # 查询目标日期该用户的已有记录
        existing_records = (
            db.query(DutySchedule)
            .filter(
                DutySchedule.date == target_date,
                DutySchedule.user_id == s.user_id,
            )
            .all()
        )

        # 检查目标日期是否已有全天请假 → 跳过并记录
        has_all_day_leave = any(
            r.schedule_type == 'LEAVE' and r.shift == 'ALL_DAY'
            for r in existing_records
        )
        if has_all_day_leave:
            skipped.append({
                "user_id": s.user_id,
                "real_name": user_name_map.get(s.user_id, ""),
                "date": target_date.isoformat(),
                "reason": "全天请假",
            })
            continue

        # 检查目标日期是否已有相同 shift 的排班 → 跳过
        has_same_shift = any(r.shift == s.shift for r in existing_records)
        if has_same_shift:
            continue

        # 创建新记录
        new_ds = DutySchedule(
            date=target_date,
            shift=s.shift,
            user_id=s.user_id,
            schedule_type=s.schedule_type,
            note=s.note,
        )
        db.add(new_ds)
        created_count += 1

    db.commit()
    logger.info(
        f"[DutySchedule] 复制周排班: created={created_count}, skipped={len(skipped)}, "
        f"source=[{source_start} ~ {source_end}], target_start={data.target_start_date}, "
        f"operator={current_user.id}"
    )
    return {
        "created": created_count,
        "skipped": skipped,
    }


@router.post("/{id}", response_model=DutyScheduleResponse, summary="更新排班记录")
def update_duty_schedule(
    id: int,
    data: DutyScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_supervisor_or_admin(current_user)

    ds = db.query(DutySchedule).filter(DutySchedule.id == id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="排班记录不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        if key == "shift" and val is not None:
            setattr(ds, key, val.value)
        else:
            setattr(ds, key, val)

    db.commit()
    db.refresh(ds)
    logger.info(f"[DutySchedule] 更新排班: id={id}, operator={current_user.id}")
    return _to_response(ds)


@router.delete("/", summary="按条件删除排班记录（无 id 时使用）")
def delete_duty_schedule_by_query(
    user_id: int = Query(..., description="用户ID"),
    date: date = Query(..., description="日期"),
    shift: str = Query(..., description="班次 MORNING/AFTERNOON/NIGHT/ALL_DAY"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_supervisor_or_admin(current_user)

    ds = (
        db.query(DutySchedule)
        .filter(
            DutySchedule.user_id == user_id,
            DutySchedule.date == date,
            DutySchedule.shift == shift,
        )
        .first()
    )
    if not ds:
        raise HTTPException(status_code=404, detail="排班记录不存在")
    db.delete(ds)
    db.commit()
    logger.info(f"[DutySchedule] 按条件删除排班: user_id={user_id}, date={date}, shift={shift}, operator={current_user.id}")
    return {"message": "排班记录已删除"}


@router.delete("/{id}", summary="删除排班记录")
def delete_duty_schedule(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_supervisor_or_admin(current_user)

    ds = db.query(DutySchedule).filter(DutySchedule.id == id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="排班记录不存在")

    db.delete(ds)
    db.commit()
    logger.info(f"[DutySchedule] 删除排班: id={id}, operator={current_user.id}")
    return {"message": "排班记录已删除"}


@router.post("/leave/batch", summary="批量登记请假")
def batch_create_leave(
    data: LeaveBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_manage_role(current_user)

    if data.start_date > data.end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    date_range = []
    cur = data.start_date
    while cur <= data.end_date:
        date_range.append(cur)
        cur += timedelta(days=1)

    created_ids = []
    created_count = 0

    for d in date_range:
        for user_id in data.user_ids:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                logger.warning(f"[Leave] 用户不存在，跳过: user_id={user_id}")
                continue
            ds = DutySchedule(
                date=d,
                shift=data.shift or "ALL_DAY",
                user_id=user_id,
                schedule_type="LEAVE",
                note=data.note,
                leave_type=data.leave_type,
                leave_status="APPROVED",
            )
            db.add(ds)
            db.flush()
            created_ids.append(ds.id)
            created_count += 1

    db.commit()
    logger.info(
        f"[Leave] 批量请假登记完成: created={created_count}, "
        f"date_range=[{data.start_date} ~ {data.end_date}], leave_type={data.leave_type}, "
        f"operator={current_user.id}"
    )
    return {"created": created_count, "ids": created_ids}


@router.get("/leave/summary", summary="当日出勤+请假概览")
def get_leave_summary(
    date: date = Query(None, description="查询日期，默认今天"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_date = date or datetime.now().date()
    now_hour = datetime.now().hour
    date_shift_now = _get_shift_by_hour(now_hour)

    tech_roles = ('technician', 'repairer', 'engineer',
                  'TECHNICIAN', 'REPAIRER', 'ENGINEER',
                  UserRole.TECHNICIAN.value)

    active_techs = (
        db.query(User)
        .filter(User.role.in_(tech_roles), User.is_active == True)
        .all()
    )
    tech_ids = [u.id for u in active_techs]
    tech_name_map = {u.id: u.real_name for u in active_techs}

    schedules = (
        db.query(DutySchedule)
        .filter(DutySchedule.date == target_date, DutySchedule.user_id.in_(tech_ids))
        .all()
    )

    schedule_users = set()
    leave_users_all_day = set()
    leaves = []

    for s in schedules:
        if s.schedule_type in ('WEEKLY_ROUTINE', 'MANUAL'):
            schedule_users.add(s.user_id)
        elif s.schedule_type == 'LEAVE':
            if s.shift == 'ALL_DAY':
                leave_users_all_day.add(s.user_id)
            leaves.append({
                "user_id": s.user_id,
                "real_name": tech_name_map.get(s.user_id, ""),
                "leave_type": s.leave_type,
                "shift": s.shift,
                "note": s.note,
            })

    on_duty_users = schedule_users - leave_users_all_day
    on_duty_total = len(on_duty_users)

    leave_deduction = 0.0
    for s in schedules:
        if s.schedule_type != 'LEAVE' or s.user_id not in on_duty_users:
            continue
        if s.shift == 'ALL_DAY':
            leave_deduction += 1.0
        elif s.shift == date_shift_now:
            leave_deduction += 0.5

    available_headcount = round(on_duty_total - leave_deduction, 1)
    availability_rate = round(available_headcount / on_duty_total * 100) if on_duty_total else 0

    return {
        "date": target_date,
        "on_duty_total": on_duty_total,
        "leaves": leaves,
        "available_headcount": available_headcount,
        "availability_rate": availability_rate,
        "date_shift_now": date_shift_now,
    }


@router.delete("/batch", summary="批量删除排班/请假记录")
def batch_delete_schedules(
    data: BatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_manager = current_user.role in ('ADMIN', 'SUPERVISOR', 'MANAGER',
                                       UserRole.ADMIN.value, UserRole.SUPERVISOR.value)

    if not data.ids:
        return {"deleted": 0}

    records = db.query(DutySchedule).filter(DutySchedule.id.in_(data.ids)).all()

    today = datetime.now().date()
    for r in records:
        if not is_manager:
            if r.user_id != current_user.id:
                raise HTTPException(status_code=403, detail="普通用户只能删除自己的记录")
            if r.schedule_type != 'LEAVE':
                raise HTTPException(status_code=403, detail="普通用户只能删除请假记录")
            if r.date <= today:
                raise HTTPException(status_code=403, detail="只能删除未来日期的请假记录")

    deleted = (
        db.query(DutySchedule)
        .filter(DutySchedule.id.in_(data.ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    logger.info(
        f"[DutySchedule] 批量删除: deleted={deleted}, ids={data.ids}, operator={current_user.id}"
    )
    return {"deleted": deleted}
