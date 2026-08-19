from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from loguru import logger
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.user import User, UserRole

router = APIRouter(prefix="/api/v1/dispatch", tags=["派工管理"])


class DispatchConfirmRequest(BaseModel):
    """派工确认请求 - 推荐验证 + 创建工单 合成事务"""
    fault_description: str
    technician_id: int
    device_id: Optional[int] = None
    device_code: Optional[str] = None
    fault_code: Optional[str] = None
    priority: str = "MEDIUM"
    location: Optional[str] = None
    tags: Optional[List[str]] = None
    fault_category: Optional[str] = None
    fault_phenomenon_type: Optional[str] = None
    fault_phenomenon: Optional[str] = None


class DispatchConfirmResponse(BaseModel):
    success: bool
    work_order_id: Optional[int] = None
    work_order_no: Optional[str] = None
    technician_name: Optional[str] = None
    error: Optional[str] = None


@router.get("/technicians", summary="获取所有可用维修员列表(主管派工下拉)")
def list_technicians(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail="仅主管或管理员可查看维修员列表")

    technicians = (
        db.query(User)
        .filter(User.role == UserRole.TECHNICIAN.value)
        .filter(User.is_active == True)
        .order_by(User.current_workload_count.asc(), User.real_name.asc())
        .all()
    )

    # 近7天已完成工单数：一次聚合查询避免 N+1
    from datetime import datetime, timedelta
    from sqlalchemy import func
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    completed_count_rows = (
        db.query(
            WorkOrder.technician_id,
            func.count(WorkOrder.id).label("cnt")
        )
        .filter(WorkOrder.status == "COMPLETED")
        .filter(WorkOrder.updated_at >= seven_days_ago)
        .group_by(WorkOrder.technician_id)
        .all()
    )
    completed_map = {row.technician_id: row.cnt for row in completed_count_rows if row.technician_id}

    result = []
    for t in technicians:
        result.append({
            "id": t.id,
            "real_name": t.real_name,
            "username": t.username,
            "employee_id": t.employee_id,
            "role": t.role,
            "phone": t.phone,
            "skills_json": t.skills_json,
            "current_workload_count": t.current_workload_count or 0,
            "last_online_at": t.last_online_at,
            "skills": t.skills,
            "recent7d_completed": completed_map.get(t.id, 0),
        })
    return result


@router.post("/confirm", response_model=DispatchConfirmResponse, summary="派工确认（推荐+创建工单 合成事务）")
def confirm_dispatch(
    data: DispatchConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """主管确认派工：验证维修员 → 在岗校验 → 创建工单 → 钉钉推送，一个事务完成"""
    if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail="仅主管或管理员可确认派工")

    # 1. 验证维修员
    technician = db.query(User).filter(User.id == data.technician_id).first()
    if not technician:
        raise HTTPException(status_code=400, detail="指派的维修员不存在")
    if not technician.is_active:
        raise HTTPException(status_code=400, detail="指派的维修员已停用")
    if technician.role not in (UserRole.TECHNICIAN.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=400, detail="被指派人必须是维修员角色")

    # 2. 在岗校验
    from app.models.duty_schedule import DutySchedule
    from datetime import datetime, date as date_type
    today = date_type.today()
    now_hour = datetime.now().hour
    today_schedules = db.query(DutySchedule).filter(
        DutySchedule.user_id == data.technician_id,
        DutySchedule.date == today,
    ).all()

    for s in today_schedules:
        if s.schedule_type == 'LEAVE' and s.shift == 'ALL_DAY':
            raise HTTPException(status_code=400, detail=f"该维修员今日全天请假，无法派工")

    # 当前时段请假校验
    def _current_shift(hour):
        if 8 <= hour < 16: return "MORNING"
        elif 16 <= hour < 24: return "AFTERNOON"
        else: return "NIGHT"

    cur_shift = _current_shift(now_hour)
    for s in today_schedules:
        if s.schedule_type == 'LEAVE' and s.shift == cur_shift:
            raise HTTPException(status_code=400, detail=f"该维修员当前时段请假（{cur_shift}），无法派工")

    # 3. 生成工单号
    today_str = today.strftime("%Y%m%d")
    prefix = f"WO-{today_str}-"
    latest = (
        db.query(WorkOrder)
        .filter(WorkOrder.work_order_no.like(f"{prefix}%"))
        .order_by(WorkOrder.work_order_no.desc())
        .first()
    )
    if latest and latest.work_order_no:
        try:
            seq = int(latest.work_order_no.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    work_order_no = f"{prefix}{seq:03d}"

    # 4. 创建工单
    work_order = WorkOrder(
        work_order_no=work_order_no,
        device_id=data.device_id,
        device_code=data.device_code,
        fault_code=data.fault_code,
        fault_description=data.fault_description,
        fault_category=data.fault_category,
        fault_phenomenon_type=data.fault_phenomenon_type,
        fault_phenomenon=data.fault_phenomenon,
        priority=data.priority or "MEDIUM",
        location=data.location,
        technician_id=data.technician_id,
        assignee_id=data.technician_id,
        tags=data.tags,
        status=WorkOrderStatus.ASSIGNED,
        created_by=current_user.id,
    )
    db.add(work_order)
    db.flush()

    # 5. 记录进度日志
    from app.api.work_orders import _add_progress_log, _update_workload
    _add_progress_log(
        db=db,
        work_order_id=work_order.id,
        from_status=WorkOrderStatus.DRAFT,
        to_status=WorkOrderStatus.ASSIGNED,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        source="WEB",
        remark=f"主管派工，指派给 {technician.real_name}",
    )
    _update_workload(db, data.technician_id, +1)

    # 6. 钉钉推送（失败不影响工单创建）：发送带进度确认按钮的互动卡片
    try:
        from app.core.dingtalk_wo_card import send_progress_card
        from app.core.config import settings
        public_url = getattr(settings, "SERVER_PUBLIC_URL", "") or ""
        send_progress_card(
            technician.dingtalk_userid or "",
            work_order,
            supervisor_name=current_user.real_name,
            public_url=public_url,
        )
    except Exception as e:
        logger.warning(f"[Dispatch] 派工进度卡片发送失败（不影响工单创建）: {e}")

    db.commit()
    db.refresh(work_order)
    logger.info(f"[Dispatch] 派工确认成功: {work_order_no} → {technician.real_name}, operator={current_user.id}")

    return DispatchConfirmResponse(
        success=True,
        work_order_id=work_order.id,
        work_order_no=work_order_no,
        technician_name=technician.real_name,
    )
