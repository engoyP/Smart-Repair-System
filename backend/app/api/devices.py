from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.device import Device
from app.models.work_order import WorkOrder
from app.models.user import User
from app.schemas import DeviceCreate, DeviceUpdate, DeviceResponse, PaginatedResponse

router = APIRouter()


VALID_RUN_STATUS = ("ONLINE", "OFFLINE", "ALARM", "FAULT", "UNKNOWN")


def _ensure_not_pure_supervisor(current_user: User):
    """纯主管只允许查看，不允许修改"""
    if current_user.role == 'SUPERVISOR':
        raise HTTPException(status_code=403, detail="主管仅具备设备查看权限，如需修改请联系管理员")


def _device_to_dict(d: Device) -> dict:
    data = {c.name: getattr(d, c.name) for c in d.__table__.columns}
    return data


@router.get("/", response_model=PaginatedResponse[DeviceResponse], summary="获取设备列表")
def list_devices(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=1000),
    device_type: Optional[str] = None,
    run_status: Optional[str] = None,
    has_fault: Optional[bool] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Device)
    if device_type:
        query = query.filter(Device.device_type == device_type)
    if run_status:
        query = query.filter(Device.run_status == run_status.upper())
    if has_fault is True:
        query = query.filter(Device.fault_tags.isnot(None))
    elif has_fault is False:
        query = query.filter((Device.fault_tags == None) | (func.jsonb_array_length(Device.fault_tags) == 0))
    if keyword:
        query = query.filter(
            Device.device_name.ilike(f"%{keyword}%") |
            Device.device_code.ilike(f"%{keyword}%")
        )
    total = query.count()
    # 按故障/告警优先排序：FAULT > ALARM > OFFLINE > UNKNOWN > ONLINE
    status_order = case(
        (Device.run_status == "FAULT", 0),
        (Device.run_status == "ALARM", 1),
        (Device.run_status == "OFFLINE", 2),
        (Device.run_status == "UNKNOWN", 3),
        (Device.run_status == "ONLINE", 4),
        else_=5,
    )
    items = query.order_by(status_order, Device.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_device_to_dict(d) for d in items], "page": page, "page_size": page_size}


@router.get("/{device_id}", response_model=DeviceResponse, summary="获取设备详情")
def get_device(device_id: int, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


@router.post("/", response_model=DeviceResponse, summary="创建设备")
def create_device(
    data: DeviceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_not_pure_supervisor(current_user)
    existing = db.query(Device).filter(Device.device_code == data.device_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="设备编码已存在")
    device = Device(**data.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.put("/{device_id}", response_model=DeviceResponse, summary="更新设备")
def update_device(
    device_id: int,
    data: DeviceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_not_pure_supervisor(current_user)
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(device, key, val)
    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", summary="删除设备")
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_not_pure_supervisor(current_user)
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    db.delete(device)
    db.commit()
    return {"message": "设备已删除"}


# ==================== 设备历史维修摘要 ====================

@router.get("/{device_id}/maintenance-summary", summary="设备历史维修摘要")
def get_device_maintenance_summary(device_id: int, db: Session = Depends(get_db)):
    """查询设备近6个月维修次数和最近一次故障摘要"""
    from datetime import datetime, timedelta
    from sqlalchemy import desc
    from app.models.work_order import WorkOrder

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    six_months_ago = datetime.utcnow() - timedelta(days=180)

    # 近6个月维修次数（已完成工单）
    recent_count = db.query(WorkOrder).filter(
        WorkOrder.device_id == device_id,
        WorkOrder.status == "COMPLETED",
        WorkOrder.updated_at >= six_months_ago,
    ).count()

    # 最近一次故障
    last_wo = db.query(WorkOrder).filter(
        WorkOrder.device_id == device_id,
        WorkOrder.status == "COMPLETED",
    ).order_by(desc(WorkOrder.updated_at)).first()

    return {
        "device_name": device.device_name,
        "recent_count": recent_count,
        "last_fault": last_wo.fault_description[:100] if last_wo else None,
        "last_date": last_wo.updated_at.isoformat() if last_wo else None,
        "last_fault_code": last_wo.fault_code if last_wo else None,
    }


# ==================== 设备监控预留接口（对接外部故障上报系统） ====================
# 设计依据：
# - 遵循证据驱动状态（经验 100101297）：无证据用 UNKNOWN，不默认 ONLINE
# - 统一中心化同步入口（经验 2007475）：外部系统只调 /sync-status，不直接写库


class DeviceMonitorStats(BaseModel):
    total: int
    online: int
    offline: int
    alarm: int
    fault: int
    unknown: int
    with_fault_tags: int


@router.get("/monitor/stats", response_model=DeviceMonitorStats, summary="设备监控统计")
def get_device_monitor_stats(
    device_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Device)
    if device_type:
        query = query.filter(Device.device_type == device_type)
    items = query.all()
    n = len(items)
    counter = {"ONLINE": 0, "OFFLINE": 0, "ALARM": 0, "FAULT": 0, "UNKNOWN": 0}
    with_fault = 0
    for d in items:
        s = d.run_status or "UNKNOWN"
        counter[s] = counter.get(s, 0) + 1
        if d.fault_tags and len(d.fault_tags) > 0:
            with_fault += 1
    return DeviceMonitorStats(
        total=n,
        online=counter["ONLINE"],
        offline=counter["OFFLINE"],
        alarm=counter["ALARM"],
        fault=counter["FAULT"],
        unknown=counter["UNKNOWN"],
        with_fault_tags=with_fault,
    )


# ---- 批量同步状态（外部系统唯一入口：统一参数、统一判定、统一幂等） ----

class DeviceStatusSyncItem(BaseModel):
    ext_system_id: Optional[str] = None
    device_code: Optional[str] = None
    device_id: Optional[int] = None
    run_status: str
    last_heartbeat: Optional[datetime] = None
    status_reason: Optional[str] = None
    monitor_extra: Optional[dict] = None


class DeviceStatusSyncResponse(BaseModel):
    success: int
    failed: int
    failures: List[dict] = []


@router.post("/monitor/sync-status", response_model=DeviceStatusSyncResponse, summary="批量同步设备状态（外部上报系统调用）")
def sync_device_status(
    items: List[DeviceStatusSyncItem],
    db: Session = Depends(get_db),
):
    """
    中心化同步入口：给外部故障上报系统调用。
    匹配优先级：ext_system_id > device_code > device_id。
    所有设备找不到时计入 failures，找到则原子更新监控字段。
    """
    now = datetime.utcnow()
    success = 0
    failures = []
    for i, item in enumerate(items):
        status_clean = (item.run_status or "").upper()
        if status_clean not in VALID_RUN_STATUS:
            failures.append({"index": i, "reason": f"无效 run_status: {item.run_status}"})
            continue
        device = None
        if item.ext_system_id:
            device = db.query(Device).filter(Device.ext_system_id == item.ext_system_id).first()
        if not device and item.device_code:
            device = db.query(Device).filter(Device.device_code == item.device_code).first()
        if not device and item.device_id:
            device = db.query(Device).filter(Device.id == item.device_id).first()
        if not device:
            failures.append({"index": i, "reason": "未找到匹配设备（ext_system_id/device_code/device_id）"})
            continue
        # 证据驱动：只写入明确提交的字段，保留证据原因
        device.run_status = status_clean
        device.status_source = "external"
        device.last_sync_time = now
        if item.last_heartbeat is not None:
            device.last_heartbeat = item.last_heartbeat
        else:
            device.last_heartbeat = now
        if item.status_reason:
            device.status_reason = item.status_reason
        if item.monitor_extra is not None:
            old = device.monitor_extra or {}
            old.update(item.monitor_extra)
            device.monitor_extra = old
        # 首次绑定 ext_system_id
        if item.ext_system_id and not device.ext_system_id:
            device.ext_system_id = item.ext_system_id
        success += 1
    db.commit()
    return DeviceStatusSyncResponse(success=success, failed=len(failures), failures=failures)


# ---- 故障标签上报（外部系统标故障时调用，同步到这里） ----

class FaultTag(BaseModel):
    code: str
    name: str
    level: Optional[str] = "WARNING"  # INFO / WARNING / ERROR / CRITICAL
    message: Optional[str] = None
    triggered_at: Optional[datetime] = None


class FaultTagReport(BaseModel):
    ext_system_id: Optional[str] = None
    device_code: Optional[str] = None
    device_id: Optional[int] = None
    tags: List[FaultTag]
    clear_existing: Optional[bool] = False  # True 时覆盖原有，False 时去重合并


@router.post("/monitor/report-faults", summary="上报设备故障标签（外部系统→本系统同步）")
def report_fault_tags(report: FaultTagReport, db: Session = Depends(get_db)):
    """
    外部故障上报系统标故障时调用：把故障标签同步到设备上。
    返回更新后的设备监控字段。
    """
    device = None
    if report.ext_system_id:
        device = db.query(Device).filter(Device.ext_system_id == report.ext_system_id).first()
    if not device and report.device_code:
        device = db.query(Device).filter(Device.device_code == report.device_code).first()
    if not device and report.device_id:
        device = db.query(Device).filter(Device.id == report.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="未找到匹配设备")

    now = datetime.utcnow()
    new_tags = [t.model_dump() for t in report.tags]
    # 补 triggered_at
    for t in new_tags:
        if not t.get("triggered_at"):
            t["triggered_at"] = now.isoformat()
        elif isinstance(t["triggered_at"], datetime):
            t["triggered_at"] = t["triggered_at"].isoformat()

    if report.clear_existing or not device.fault_tags:
        merged = new_tags
    else:
        # 按 code 去重合并
        seen = {}
        for old in device.fault_tags or []:
            seen[old.get("code")] = old
        for n in new_tags:
            seen[n.get("code")] = n
        merged = list(seen.values())

    device.fault_tags = merged
    device.last_sync_time = now
    # 故障优先级：含 CRITICAL/ERROR 标签 → FAULT；含 WARNING → ALARM；否则保留原状态
    levels = {t.get("level", "").upper() for t in merged}
    if levels & {"CRITICAL", "ERROR"}:
        if device.run_status != "FAULT":
            device.run_status = "FAULT"
            device.status_reason = f"外部系统上报故障标签: {', '.join(sorted(levels & {'CRITICAL','ERROR'}))}"
    elif "WARNING" in levels and device.run_status not in ("FAULT",):
        device.run_status = "ALARM"
        if not device.status_reason:
            device.status_reason = "外部系统上报告警标签"
    device.status_source = "external"
    db.commit()
    db.refresh(device)
    return _device_to_dict(device)


@router.post("/monitor/{device_id}/clear-faults", summary="清理设备故障标签（恢复时调用）")
def clear_fault_tags(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_not_pure_supervisor(current_user)
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    device.fault_tags = []
    now = datetime.utcnow()
    device.last_sync_time = now
    # 证据链：恢复时若无新证据，保守恢复为 UNKNOWN 或保留原状态，不默认 ONLINE
    if device.run_status in ("ALARM", "FAULT"):
        device.run_status = "UNKNOWN"
        device.status_reason = "故障标签已清理，等待外部系统确认恢复"
        device.status_source = "manual"
    db.commit()
    db.refresh(device)
    return _device_to_dict(device)