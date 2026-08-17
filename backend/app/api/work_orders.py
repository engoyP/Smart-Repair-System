from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import cast, Date
from typing import Optional, List, Dict, Any
from loguru import logger
from datetime import date, datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.device import Device
from app.models.spare_part import SparePart
from app.models.user import User, UserRole
from app.models.progress_log import WorkOrderProgressLog
from app.models.duty_schedule import DutySchedule
from app.schemas import (
    WorkOrderCreate, WorkOrderUpdate, WorkOrderResponse, PaginatedResponse,
    TicketAnalysisResponse, WorkOrderTransition, WorkOrderDispatchCreate,
    WorkOrderProgressLogResponse,
)
from app.agents.ticket_agent import ticket_agent
from app.agents.knowledge_extractor import knowledge_extractor
from app.agents.tools import extract_error_codes
from app.models.knowledge import KnowledgeItem, KnowledgeStatus

router = APIRouter()


def _wo_to_dict(w: WorkOrder) -> dict:
    return {c.name: getattr(w, c.name) for c in w.__table__.columns}


def _get_current_shift() -> str:
    """根据当前小时判断时段：MORNING / AFTERNOON / NIGHT"""
    hour = datetime.now().hour
    if 8 <= hour < 12:
        return "MORNING"
    elif 12 <= hour < 18:
        return "AFTERNOON"
    else:
        return "NIGHT"


@router.get("/", response_model=PaginatedResponse[WorkOrderResponse], summary="获取工单列表")
def list_work_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    device_type: Optional[str] = Query(None, description="设备类型筛选"),
    date_from: Optional[date] = Query(None, description="创建日期起始"),
    date_to: Optional[date] = Query(None, description="创建日期截止"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(WorkOrder)
    if status:
        query = query.filter(WorkOrder.status == status)
    if keyword:
        query = query.filter(
            WorkOrder.work_order_no.ilike(f"%{keyword}%") |
            WorkOrder.fault_description.ilike(f"%{keyword}%")
        )
    if device_type:
        query = query.join(WorkOrder.device).filter(Device.device_type == device_type)
    if date_from:
        query = query.filter(cast(WorkOrder.created_at, Date) >= date_from)
    if date_to:
        query = query.filter(cast(WorkOrder.created_at, Date) <= date_to)
    total = query.count()
    items = query.order_by(WorkOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    # 批量查询创建者/维修员信息（工号+姓名，用于前端权限判断和名字显示）
    user_ids = {w.created_by for w in items if w.created_by} | {w.technician_id for w in items if w.technician_id}
    user_emp_map = {}
    user_name_map = {}
    if user_ids:
        users_q = db.query(User).filter(User.id.in_(user_ids)).all()
        user_emp_map = {u.id: u.employee_id for u in users_q}
        user_name_map = {u.id: u.real_name for u in users_q}
    result_items = []
    for w in items:
        d = _wo_to_dict(w)
        d['created_by_employee_id'] = user_emp_map.get(w.created_by) if w.created_by else None
        d['technician_name'] = user_name_map.get(w.technician_id) if w.technician_id else None
        result_items.append(d)
    return {"total": total, "items": result_items, "page": page, "page_size": page_size}


# ========== 进度看板 ==========

# display_status 中文映射
_DISPLAY_STATUS_MAP = {
    "SUBMITTED": "待派工",
    "ASSIGNED": "待接受",
    "ACCEPTED": "已接单",
    "ARRIVED": "已到达",
    "INSPECTING": "检查中",
    "IN_PROGRESS": "维修中",
    "COMPLETED": "已完成",
}


def _build_board_item(
    w: WorkOrder,
    tech_name_map: Dict[int, str],
    logs: List[WorkOrderProgressLog],
    now: datetime,
) -> dict:
    """构造看板工单项数据"""
    status_val = w.status.value if w.status else None

    # fault_description 截断100字
    fault_desc = w.fault_description or ""
    if len(fault_desc) > 100:
        fault_desc = fault_desc[:100]

    # 构造时间轴 [{status, timestamp, operator_name}]
    progress_timeline = [
        {
            "status": l.to_status.value if l.to_status else None,
            "timestamp": l.created_at,
            "operator_name": l.operator_name,
        }
        for l in logs
    ]

    # is_overtime: ASSIGNED状态且 created_at 距现在超过15分钟
    is_overtime = False
    if status_val == WorkOrderStatus.ASSIGNED.value and w.created_at:
        is_overtime = (now - w.created_at).total_seconds() > 15 * 60

    return {
        "id": w.id,
        "work_order_no": w.work_order_no,
        "device_code": w.device_code,
        "fault_description": fault_desc,
        "status": status_val,
        "display_status": _DISPLAY_STATUS_MAP.get(status_val, status_val),
        "technician_name": tech_name_map.get(w.technician_id) if w.technician_id else None,
        "created_at": w.created_at,
        "progress_timeline": progress_timeline,
        "is_overtime": is_overtime,
    }


@router.get("/progress-board", summary="进度看板（4列）")
def get_progress_board(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一次性返回4列工单数据：待派工/待接受/进行中/已完成"""
    today_start = datetime.combine(date.today(), datetime.min.time())

    # 查询今天创建的工单
    work_orders = (
        db.query(WorkOrder)
        .filter(WorkOrder.created_at >= today_start)
        .order_by(WorkOrder.created_at.asc())
        .all()
    )

    # 维修员姓名映射
    tech_ids = {w.technician_id for w in work_orders if w.technician_id}
    tech_name_map: Dict[int, str] = {}
    if tech_ids:
        techs = db.query(User).filter(User.id.in_(tech_ids)).all()
        tech_name_map = {t.id: t.real_name for t in techs}

    # 批量查询所有工单的进度日志（避免N+1查询）
    wo_ids = [w.id for w in work_orders]
    logs_by_wo: Dict[int, List[WorkOrderProgressLog]] = {}
    if wo_ids:
        all_logs = (
            db.query(WorkOrderProgressLog)
            .filter(WorkOrderProgressLog.work_order_id.in_(wo_ids))
            .order_by(WorkOrderProgressLog.work_order_id, WorkOrderProgressLog.created_at.asc())
            .all()
        )
        for log in all_logs:
            logs_by_wo.setdefault(log.work_order_id, []).append(log)

    # 状态分组
    in_progress_statuses = {
        WorkOrderStatus.ACCEPTED.value,
        WorkOrderStatus.ARRIVED.value,
        WorkOrderStatus.INSPECTING.value,
        WorkOrderStatus.IN_PROGRESS.value,
    }

    submitted_list: List[dict] = []
    assigned_list: List[dict] = []
    in_progress_list: List[dict] = []
    completed_list: List[dict] = []
    now = datetime.now()

    for w in work_orders:
        status_val = w.status.value if w.status else None
        item = _build_board_item(w, tech_name_map, logs_by_wo.get(w.id, []), now)

        if status_val == WorkOrderStatus.SUBMITTED.value:
            submitted_list.append(item)
        elif status_val == WorkOrderStatus.ASSIGNED.value:
            assigned_list.append(item)
        elif status_val in in_progress_statuses:
            in_progress_list.append(item)
        elif status_val == WorkOrderStatus.COMPLETED.value:
            completed_list.append(item)

    return {
        "stats": {
            "submitted": len(submitted_list),
            "assigned": len(assigned_list),
            "in_progress": len(in_progress_list),
            "completed_today": len(completed_list),
        },
        "submitted": submitted_list,
        "assigned": assigned_list,
        "in_progress": in_progress_list,
        "completed": completed_list,
    }


@router.get("/{work_order_id}", response_model=WorkOrderResponse, summary="获取工单详情")
def get_work_order(work_order_id: int, db: Session = Depends(get_db)):
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    resp = WorkOrderResponse.model_validate(work_order)
    if work_order.created_by:
        creator = db.query(User).filter(User.id == work_order.created_by).first()
        resp.created_by_employee_id = creator.employee_id if creator else None
    # 维修员姓名（维修员=创建者，改名字后工单自动同步新名字）
    if work_order.technician_id:
        tech = db.query(User).filter(User.id == work_order.technician_id).first()
        resp.technician_name = tech.real_name if tech else None
    return resp


@router.post("/", response_model=WorkOrderResponse, summary="创建草稿工单")
def create_work_order(data: WorkOrderCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """创建工单草稿，状态为 DRAFT，不触发 AI 分析"""
    # 自动生成工单编号: WO-YYYYMMDD-NNN
    if not data.work_order_no:
        today_str = date.today().strftime("%Y%m%d")
        prefix = f"WO-{today_str}-"
        latest = db.query(WorkOrder).filter(
            WorkOrder.work_order_no.like(f"{prefix}%")
        ).order_by(WorkOrder.work_order_no.desc()).first()
        if latest and latest.work_order_no:
            try:
                seq = int(latest.work_order_no.split("-")[-1]) + 1
            except ValueError:
                seq = 1
        else:
            seq = 1
        data.work_order_no = f"{prefix}{seq:03d}"
    existing = db.query(WorkOrder).filter(WorkOrder.work_order_no == data.work_order_no).first()
    if existing:
        raise HTTPException(status_code=400, detail="工单编号已存在")
    work_order = WorkOrder(**data.model_dump(exclude_unset=True))
    work_order.created_by = current_user.id
    # 维修员强制为当前创建者（号主），不可指定他人
    work_order.technician_id = current_user.id
    if work_order.status not in (WorkOrderStatus.DRAFT, None):
        work_order.status = WorkOrderStatus.DRAFT
    db.add(work_order)
    db.commit()
    db.refresh(work_order)
    logger.info(f"[WorkOrder] 创建草稿: {work_order.work_order_no}")
    return work_order


@router.put("/{work_order_id}", response_model=WorkOrderResponse, summary="更新工单（逐步填写）")
def update_work_order(work_order_id: int, data: WorkOrderUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """维修过程中逐步保存表单内容。创建者、被指派的维修员或管理员可编辑。"""
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    if work_order.status == WorkOrderStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="已完成工单不可修改")

    # 权限校验：创建者 / 被指派维修员（主管派工场景）/ 管理员可编辑
    is_assigned_tech = (
        (work_order.technician_id and work_order.technician_id == current_user.id)
        or (work_order.assignee_id and work_order.assignee_id == current_user.id)
    )
    if (
        work_order.created_by
        and current_user.id != work_order.created_by
        and not is_assigned_tech
        and current_user.role != UserRole.ADMIN.value
    ):
        raise HTTPException(status_code=403, detail="仅工单创建者、被指派维修员或管理员可编辑此工单")

    for key, val in data.model_dump(exclude_unset=True).items():
        # 维修员和创建者不可通过更新修改（维修员锁定为创建者）
        if key in ("technician_id", "created_by"):
            continue
        setattr(work_order, key, val)
    if work_order.status == WorkOrderStatus.DRAFT and any([work_order.fault_description, work_order.device_id]):
        work_order.status = WorkOrderStatus.IN_PROGRESS
    db.commit()
    db.refresh(work_order)
    return work_order


@router.post("/{work_order_id}/analyze", response_model=TicketAnalysisResponse, summary="AI 分析工单")
def analyze_work_order(work_order_id: int, db: Session = Depends(get_db)):
    """对工单执行 AI 标准化分析，返回分析结果但不改变状态"""
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")

    wo_data = {
        "fault_description": work_order.fault_description,
        "fault_code": work_order.fault_code,
        "fault_phenomenon": work_order.fault_phenomenon,
        "root_cause": work_order.root_cause,
        "solution_steps": work_order.solution_steps,
    }
    analysis = ticket_agent.analyze(wo_data)

    # 保存分析结果
    work_order.analysis_result = {
        "device_type": analysis.device_type,
        "fault_category": analysis.fault_category,
        "severity": analysis.severity,
        "completeness_score": analysis.completeness_score,
        "missing_fields": analysis.missing_fields,
        "validation_notes": analysis.validation_notes,
        "raw_reasoning": analysis.raw_reasoning,
        "suggested_actions": analysis.suggested_actions,
        "standardized_fields": {
            "fault_code": analysis.standardized_fault_code,
            "fault_phenomenon": analysis.standardized_fault_phenomenon,
            "root_cause": analysis.standardized_root_cause,
            "solution_steps": analysis.standardized_solution_steps,
        },
    }
    work_order.confidence = analysis.confidence
    db.commit()
    db.refresh(work_order)

    return TicketAnalysisResponse(
        work_order_id=work_order.id,
        standardized_fault_code=analysis.standardized_fault_code,
        standardized_fault_phenomenon=analysis.standardized_fault_phenomenon,
        standardized_root_cause=analysis.standardized_root_cause,
        standardized_solution_steps=analysis.standardized_solution_steps,
        device_type=analysis.device_type,
        fault_category=analysis.fault_category,
        tags=analysis.tags,
        severity=analysis.severity,
        completeness_score=analysis.completeness_score,
        missing_fields=analysis.missing_fields,
        validation_notes=analysis.validation_notes,
        confidence=analysis.confidence,
        raw_reasoning=analysis.raw_reasoning,
        suggested_actions=analysis.suggested_actions,
    )


@router.post("/{work_order_id}/complete", summary="提交完成工单（AI 分析+去重+收录知识）")
def complete_work_order(work_order_id: int, db: Session = Depends(get_db)):
    """
    维修人员确认全部填写完成并提交：
    1. AI 标准化分析（补全缺失的标准化字段）
    2. 自动提取结构化知识 + 去重检测
    3. 非重复 → 发布到知识库 → 同步 Milvus
    4. 工单状态改为 COMPLETED
    返回 knowledge_synced 标识知识是否被收录
    """
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    if work_order.status == WorkOrderStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="工单已完成")

    # 1. AI 标准化分析
    wo_data = {
        "fault_description": work_order.fault_description,
        "fault_code": work_order.fault_code,
        "fault_phenomenon": work_order.fault_phenomenon,
        "root_cause": work_order.root_cause,
        "solution_steps": work_order.solution_steps,
    }
    try:
        analysis = ticket_agent.analyze(wo_data)
        work_order.confidence = analysis.confidence
        work_order.analysis_result = {
            "device_type": analysis.device_type,
            "fault_category": analysis.fault_category,
            "severity": analysis.severity,
            "completeness_score": analysis.completeness_score,
            "missing_fields": analysis.missing_fields,
            "validation_notes": analysis.validation_notes,
            "raw_reasoning": analysis.raw_reasoning,
            "suggested_actions": analysis.suggested_actions,
            "standardized_fields": {
                "fault_code": analysis.standardized_fault_code,
                "fault_phenomenon": analysis.standardized_fault_phenomenon,
                "root_cause": analysis.standardized_root_cause,
                "solution_steps": analysis.standardized_solution_steps,
            },
        }
        # 补全标准化字段
        if analysis.standardized_fault_code and not work_order.fault_code:
            work_order.fault_code = analysis.standardized_fault_code
        if analysis.standardized_fault_phenomenon and not work_order.fault_phenomenon:
            work_order.fault_phenomenon = analysis.standardized_fault_phenomenon
        if analysis.standardized_root_cause and not work_order.root_cause:
            work_order.root_cause = analysis.standardized_root_cause
        if analysis.standardized_solution_steps and not work_order.solution_steps:
            work_order.solution_steps = analysis.standardized_solution_steps
        if analysis.tags:
            work_order.tags = analysis.tags
    except Exception as e:
        logger.warning(f"[WorkOrder] 提交时 AI 分析失败: {e}")

    # 2. 自动提取知识并发布（含去重检测）
    knowledge_synced = False
    try:
        knowledge_synced = _auto_publish_knowledge(work_order, db)
    except Exception as e:
        logger.warning(f"[WorkOrder] 知识收录失败: {e}")

    # 2.5 扣减备件库存
    deduction_details = _deduct_spare_parts(work_order, db)

    # 2.6 收录故障码到映射表（一一对应，不可修改）
    _ensure_fault_code_mappings(work_order, db)

    # 3. 标记完成
    work_order.status = WorkOrderStatus.COMPLETED
    db.commit()
    db.refresh(work_order)
    logger.info(f"[WorkOrder] 工单 {work_order.work_order_no} 已提交完成，knowledge_synced={knowledge_synced}")
    return {
        "id": work_order.id,
        "work_order_no": work_order.work_order_no,
        "status": "COMPLETED",
        "knowledge_synced": knowledge_synced,
        "message": "知识已收录到知识库" if knowledge_synced else "提交成功（检测到相似知识，未重复收录）",
        "inventory_deducted": deduction_details,
    }


@router.delete("/{work_order_id}", summary="删除工单")
def delete_work_order(work_order_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    # 权限校验：仅创建者或管理员可删除
    if work_order.created_by and current_user.id != work_order.created_by and current_user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅工单创建者或管理员可删除此工单")
    db.delete(work_order)
    db.commit()
    return {"message": "工单已删除"}


# ========== 内部函数 ==========

def _join_fault_codes(*parts) -> str:
    """合并多来源的故障码/设备错误码（去重，逗号分隔）——系统故障码 + 设备错误码"""
    seen, out = set(), []
    for p in parts:
        if not p:
            continue
        for c in str(p).replace("，", ",").split(","):
            c = c.strip()
            if c and c not in seen:
                seen.add(c)
                out.append(c)
    return ", ".join(out)


def _auto_publish_knowledge(wo: WorkOrder, db: Session) -> bool:
    """
    从工单提取知识 → 去重 → 直接发布到知识库
    返回 True 表示已收录，False 表示跳过（重复或提取失败）
    """
    # 同一工单不重复提取
    existing = db.query(KnowledgeItem).filter(
        KnowledgeItem.source_type == "WORK_ORDER",
        KnowledgeItem.source_id == wo.id,
    ).first()
    if existing:
        logger.info(f"[WorkOrder] 工单 {wo.work_order_no} 已提取过知识 #{existing.id}，跳过")
        return False

    analysis = wo.analysis_result if isinstance(wo.analysis_result, dict) else {}
    wo_data = {
        "fault_description": wo.fault_description,
        "fault_code": wo.fault_code,
        "device_error_code": wo.device_error_code,   # 设备运行日志错误码（SV0436 等），提取器可识别
        "log_text": wo.log_text,                     # 日志原文：仅用于抠码/信号词，不整段进正文
        "fault_phenomenon": wo.fault_phenomenon,
        "root_cause": wo.root_cause,
        "solution_steps": wo.solution_steps,
        "device_type": analysis.get("device_type", ""),
        "tags": wo.tags or [],
    }

    extracted = knowledge_extractor.extract(wo_data)
    if not extracted.title:
        logger.warning(f"[WorkOrder] 工单 {wo.work_order_no} 知识提取返回空内容")
        return False

    # 去重检测
    from app.api.knowledge import _check_duplicate
    dedup = _check_duplicate(extracted, db)

    if dedup.has_duplicate:
        true_dups = [m for m in dedup.matched_items if m.get("is_true_duplicate")]
        logger.info(
            f"[WorkOrder] 检测到真重复知识 (相似度={dedup.similarity_score:.2f}): "
            f"{[m.get('title','') for m in true_dups[:2]]}，跳过自动收录"
        )
        return False

    # 创建并发布知识
    # 知识条目的故障码 = 系统故障码 + 设备错误码合并（让检索"报SV0436"能命中该工单案例）
    knowledge = KnowledgeItem(
        title=extracted.title,
        content=extracted.content,
        device_type=extracted.device_type,
        fault_code=_join_fault_codes(extracted.fault_code, wo.device_error_code),
        fault_tags=extracted.fault_tags,
        source_type="WORK_ORDER",
        source_id=wo.id,
        status=KnowledgeStatus.PUBLISHED,
        extraction_meta={
            "work_order_no": wo.work_order_no,
            "dedup_score": dedup.similarity_score,
            "keywords": extracted.keywords,
            "device_error_code": wo.device_error_code,
            "log_error_codes": extract_error_codes(wo.log_text or "") or [],
        },
    )
    db.add(knowledge)
    db.commit()
    db.refresh(knowledge)

    # 同步到 Milvus
    try:
        from app.api.knowledge import _sync_to_milvus
        _sync_to_milvus(knowledge, db)
    except Exception as e:
        logger.warning(f"[WorkOrder] 知识向量同步失败: {e}")

    logger.info(f"[WorkOrder] 从工单 {wo.work_order_no} 自动收录知识 #{knowledge.id}: {knowledge.title[:40]}...")
    return True


def _deduct_spare_parts(wo: WorkOrder, db: Session) -> List[dict]:
    """
    工单完成时，扣减 used_parts 中备件的库存数量
    返回扣减明细列表
    """
    used_parts = wo.used_parts
    if not used_parts or not isinstance(used_parts, list) or len(used_parts) == 0:
        return []

    details = []
    for part in used_parts:
        code = part.get("code", "").strip()
        qty = part.get("qty", 0)
        if not code or qty <= 0:
            continue

        spare = db.query(SparePart).filter(SparePart.part_code == code).first()
        if not spare:
            logger.warning(f"[WorkOrder] 备件 {code} 不存在于库存中，跳过扣减")
            details.append({
                "part_code": code,
                "part_name": part.get("name", ""),
                "qty": qty,
                "status": "skipped",
                "reason": "备件不存在于库存",
            })
            continue

        # 确保库存不会为负
        actual_deduct = min(qty, spare.stock_quantity)
        spare.stock_quantity -= actual_deduct

        if actual_deduct < qty:
            logger.warning(
                f"[WorkOrder] 备件 {code} 库存不足: 需要 {qty}, 实际扣减 {actual_deduct}, 剩余 {spare.stock_quantity}"
            )

        details.append({
            "part_code": code,
            "part_name": spare.part_name,
            "deducted": actual_deduct,
            "requested": qty,
            "remaining_stock": spare.stock_quantity,
            "status": "partial" if actual_deduct < qty else "deducted",
        })
        logger.info(
            f"[WorkOrder] 备件扣减: {code} {spare.part_name} -{actual_deduct} (剩余 {spare.stock_quantity})"
        )

    return details


def _ensure_fault_code_mappings(wo: WorkOrder, db: Session):
    """工单完成时，收录故障码到映射表（一一对应，不可修改）"""
    from app.api.fault_codes import ensure_fault_code_mapping

    codes = wo.fault_code
    if not codes:
        return

    # 解析逗号分隔的故障码
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    description = f"{wo.fault_description or ''} {wo.fault_phenomenon or ''}".strip()
    if not description:
        description = wo.fault_description or ""

    # 获取设备类型
    device_type = ""
    if wo.analysis_result and isinstance(wo.analysis_result, dict):
        device_type = wo.analysis_result.get("device_type", "")

    for code in code_list:
        try:
            ensure_fault_code_mapping(
                db, fault_code=code, fault_description=description,
                device_type=device_type, source="system",
            )
        except Exception as e:
            logger.warning(f"[WorkOrder] 故障码收录失败 {code}: {e}")


# ========== Phase1 工单流转与派工 ==========

VALID_TRANSITIONS: Dict[str, List[str]] = {
    WorkOrderStatus.DRAFT.value: [WorkOrderStatus.SUBMITTED.value, WorkOrderStatus.ASSIGNED.value],
    WorkOrderStatus.SUBMITTED.value: [WorkOrderStatus.ASSIGNED.value, WorkOrderStatus.REJECTED.value],
    WorkOrderStatus.ASSIGNED.value: [WorkOrderStatus.ACCEPTED.value, WorkOrderStatus.REJECTED.value],
    WorkOrderStatus.ACCEPTED.value: [WorkOrderStatus.ARRIVED.value, WorkOrderStatus.REJECTED.value],
    WorkOrderStatus.ARRIVED.value: [WorkOrderStatus.INSPECTING.value, WorkOrderStatus.REJECTED.value],
    WorkOrderStatus.INSPECTING.value: [WorkOrderStatus.IN_PROGRESS.value, WorkOrderStatus.REJECTED.value],
    WorkOrderStatus.IN_PROGRESS.value: [WorkOrderStatus.ARCHIVING.value, WorkOrderStatus.REJECTED.value],
    WorkOrderStatus.ARCHIVING.value: [WorkOrderStatus.ARCHIVED.value],
    WorkOrderStatus.COMPLETED.value: [],
    WorkOrderStatus.REJECTED.value: [],
    WorkOrderStatus.STANDARDIZED.value: [],
    WorkOrderStatus.CLASSIFIED.value: [],
    WorkOrderStatus.APPROVED.value: [],
    WorkOrderStatus.ARCHIVED.value: [],
}

WORKLOAD_INCREASE_STATUSES = {WorkOrderStatus.ASSIGNED.value}
WORKLOAD_DECREASE_STATUSES = {WorkOrderStatus.COMPLETED.value, WorkOrderStatus.REJECTED.value}


def _is_allowed_transition(from_status: str, to_status: str) -> bool:
    allowed = VALID_TRANSITIONS.get(from_status, [])
    return to_status in allowed


def _add_progress_log(
    db: Session,
    work_order_id: int,
    from_status: Optional[str],
    to_status: str,
    operator_id: Optional[int],
    operator_name: Optional[str],
    source: str,
    remark: Optional[str] = None,
    location: Optional[str] = None,
    attachments: Any = None,
) -> WorkOrderProgressLog:
    log = WorkOrderProgressLog(
        work_order_id=work_order_id,
        from_status=from_status,
        to_status=to_status,
        operator_id=operator_id,
        operator_name=operator_name,
        source=source,
        remark=remark,
        location=location,
        attachments=attachments,
    )
    db.add(log)
    db.flush()
    return log


def _update_workload(db: Session, technician_id: Optional[int], delta: int):
    if not technician_id or delta == 0:
        return
    tech = db.query(User).filter(User.id == technician_id).first()
    if tech:
        new_count = max(0, (tech.current_workload_count or 0) + delta)
        tech.current_workload_count = new_count
        db.flush()


@router.post("/{work_order_id}/transition", response_model=WorkOrderResponse, summary="工单状态流转")
def transition_work_order(
    work_order_id: int,
    data: WorkOrderTransition,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _do_transition(work_order_id, data, db, current_user)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[Transition] 工单 #{work_order_id} 流转异常: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"工单流转内部错误: {e}")


def _do_transition(work_order_id: int, data: WorkOrderTransition, db: Session, current_user: User):
    try:
        to_status_val = data.to_status.upper()
        to_status_enum = WorkOrderStatus(to_status_val)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的目标状态: {data.to_status}")

    work_order = (
        db.query(WorkOrder)
        .filter(WorkOrder.id == work_order_id)
        .first()
    )
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")

    from_status_val = work_order.status.value if work_order.status else None

    if from_status_val == to_status_val:
        return _build_work_order_response(work_order, db)

    if not _is_allowed_transition(from_status_val, to_status_val):
        raise HTTPException(
            status_code=400,
            detail=f"非法状态流转: {from_status_val} → {to_status_val}，允许的目标状态: {VALID_TRANSITIONS.get(from_status_val, [])}"
        )

    is_admin = current_user.role == UserRole.ADMIN.value
    is_supervisor = current_user.role == UserRole.SUPERVISOR.value
    is_technician = current_user.role == UserRole.TECHNICIAN.value
    is_assigned_tech = work_order.technician_id == current_user.id

    if to_status_val == WorkOrderStatus.ACCEPTED.value:
        if not (is_assigned_tech or is_admin):
            raise HTTPException(status_code=403, detail="仅被指派的维修员或管理员可接单")

    elif to_status_val in (WorkOrderStatus.ARRIVED.value, WorkOrderStatus.INSPECTING.value, WorkOrderStatus.IN_PROGRESS.value):
        if not (is_assigned_tech or is_admin):
            raise HTTPException(status_code=403, detail="仅维修员或管理员可推进到此状态")

    elif to_status_val == WorkOrderStatus.ARCHIVING.value:
        # 完成维修 → 待归档：仅被指派维修员或管理员可操作
        if not (is_assigned_tech or is_admin):
            raise HTTPException(status_code=403, detail="仅维修员或管理员可将工单标记为待归档")

    elif to_status_val == WorkOrderStatus.ARCHIVED.value:
        raise HTTPException(status_code=400, detail="归档完成请使用工单归档接口，需 AI 校验完成度达标")

    elif to_status_val == WorkOrderStatus.COMPLETED.value:
        pass

    elif to_status_val == WorkOrderStatus.REJECTED.value:
        if not (is_assigned_tech or is_admin or is_supervisor):
            raise HTTPException(status_code=403, detail="仅维修员、主管或管理员可退回")

    elif to_status_val == WorkOrderStatus.ASSIGNED.value:
        if not (is_supervisor or is_admin):
            raise HTTPException(status_code=403, detail="仅主管或管理员可派工/改派")

    old_technician_id = work_order.technician_id
    from_status_enum = work_order.status

    if to_status_val == WorkOrderStatus.COMPLETED.value:
        try:
            complete_result = complete_work_order_internal(work_order_id, db)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[Transition] 调用complete逻辑失败，继续手动标记完成: {e}")
            work_order.status = to_status_enum
            db.flush()
    else:
        work_order.status = to_status_enum
        db.flush()

    _add_progress_log(
        db=db,
        work_order_id=work_order.id,
        from_status=from_status_enum,
        to_status=to_status_enum,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        source=data.source or "WEB",
        remark=data.remark,
        location=data.location,
        attachments=data.attachments,
    )

    if from_status_val in WORKLOAD_INCREASE_STATUSES:
        _update_workload(db, old_technician_id, -1)
    if to_status_val in WORKLOAD_INCREASE_STATUSES:
        _update_workload(db, work_order.technician_id, +1)
    if to_status_val in WORKLOAD_DECREASE_STATUSES and from_status_val not in WORKLOAD_DECREASE_STATUSES:
        _update_workload(db, old_technician_id, -1)

    db.commit()
    db.refresh(work_order)

    # 状态变更后，异步刷新维修员钉钉上的派工进度卡片（Web 端操作实时反映到钉钉，不阻塞接口响应）
    # 钉钉卡片回调走 DINGTALK_CARD 来源，卡片已由 dingtalk_wo_card._dispatch_action 异步刷新，此处跳过避免重复。
    if data.source != "DINGTALK_CARD":
        try:
            from app.core.dingtalk_wo_card import _refresh_card_async
            from app.models.user import User as _User
            _tech = db.query(_User).filter(_User.id == work_order.technician_id).first()
            if _tech and _tech.dingtalk_userid:
                _refresh_card_async(work_order.id, work_order.work_order_no)
        except Exception as e:
            logger.warning(f"[Transition] 钉钉进度卡片刷新失败（不影响工单状态）: {e}")

    logger.info(f"[WorkOrder] 状态流转 #{work_order.id}: {from_status_val} → {to_status_val} by {current_user.real_name}")
    return _build_work_order_response(work_order, db)


def complete_work_order_internal(work_order_id: int, db: Session):
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    if work_order.status == WorkOrderStatus.COMPLETED:
        return work_order

    wo_data = {
        "fault_description": work_order.fault_description,
        "fault_code": work_order.fault_code,
        "fault_phenomenon": work_order.fault_phenomenon,
        "root_cause": work_order.root_cause,
        "solution_steps": work_order.solution_steps,
    }
    try:
        analysis = ticket_agent.analyze(wo_data)
        work_order.confidence = analysis.confidence
        work_order.analysis_result = {
            "device_type": analysis.device_type,
            "fault_category": analysis.fault_category,
            "severity": analysis.severity,
            "completeness_score": analysis.completeness_score,
            "missing_fields": analysis.missing_fields,
            "validation_notes": analysis.validation_notes,
            "raw_reasoning": analysis.raw_reasoning,
            "suggested_actions": analysis.suggested_actions,
            "standardized_fields": {
                "fault_code": analysis.standardized_fault_code,
                "fault_phenomenon": analysis.standardized_fault_phenomenon,
                "root_cause": analysis.standardized_root_cause,
                "solution_steps": analysis.standardized_solution_steps,
            },
        }
        if analysis.standardized_fault_code and not work_order.fault_code:
            work_order.fault_code = analysis.standardized_fault_code
        if analysis.standardized_fault_phenomenon and not work_order.fault_phenomenon:
            work_order.fault_phenomenon = analysis.standardized_fault_phenomenon
        if analysis.standardized_root_cause and not work_order.root_cause:
            work_order.root_cause = analysis.standardized_root_cause
        if analysis.standardized_solution_steps and not work_order.solution_steps:
            work_order.solution_steps = analysis.standardized_solution_steps
        if analysis.tags:
            work_order.tags = analysis.tags
    except Exception as e:
        logger.warning(f"[WorkOrder] 提交时 AI 分析失败: {e}")

    try:
        _auto_publish_knowledge(work_order, db)
    except Exception as e:
        logger.warning(f"[WorkOrder] 知识收录失败: {e}")

    try:
        _deduct_spare_parts(work_order, db)
    except Exception as e:
        logger.warning(f"[WorkOrder] 备件扣减失败: {e}")

    try:
        _ensure_fault_code_mappings(work_order, db)
    except Exception as e:
        logger.warning(f"[WorkOrder] 故障码映射失败: {e}")

    work_order.status = WorkOrderStatus.COMPLETED
    db.flush()
    logger.info(f"[WorkOrder] 工单 {work_order.work_order_no} 已完成(流转接口)")
    return work_order


# ========== 工单归档：关键字段齐全性校验 + 归档完成 ==========

ARCHIVE_REQUIRED_FIELDS = [
    ("fault_description", "故障描述"),
    ("fault_phenomenon", "故障现象"),
    ("root_cause", "根本原因"),
    ("solution_steps", "解决方案"),
    ("repair_result", "维修结果"),
    ("work_hours", "维修工时"),
]


def _archive_field_check(work_order: WorkOrder) -> dict:
    """校验工单归档关键字段是否齐全。返回 {passed, missing_fields, completeness, total_fields}"""
    missing = []
    for field, label in ARCHIVE_REQUIRED_FIELDS:
        val = getattr(work_order, field, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(label)
    total = len(ARCHIVE_REQUIRED_FIELDS)
    filled = total - len(missing)
    return {
        "passed": len(missing) == 0,
        "missing_fields": missing,
        "completeness": round(filled / total, 2),
        "total_fields": total,
    }


@router.post("/{work_order_id}/archive-check", summary="工单归档校验（关键字段齐全性）")
def archive_check(
    work_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """待归档工单的归档校验：检查关键字段是否齐全，返回完成度与缺失项。"""
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    if work_order.status != WorkOrderStatus.ARCHIVING:
        raise HTTPException(status_code=400, detail="仅待归档状态工单可执行归档校验")

    is_admin = current_user.role == UserRole.ADMIN.value
    is_assigned_tech = work_order.technician_id == current_user.id or work_order.assignee_id == current_user.id
    if not (is_assigned_tech or is_admin):
        raise HTTPException(status_code=403, detail="仅被指派的维修员或管理员可归档")

    result = _archive_field_check(work_order)
    logger.info(
        f"[Archive] 归档校验 #{work_order_id}: passed={result['passed']}, "
        f"completeness={result['completeness']}, missing={result['missing_fields']} by {current_user.real_name}"
    )
    return result


@router.post("/{work_order_id}/archive-complete", summary="工单归档完成（校验达标后归档）")
def archive_complete(
    work_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """归档完成：必须通过关键字段齐全性校验（完成度达标）才允许，否则拒绝并列出缺失项。"""
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    if work_order.status != WorkOrderStatus.ARCHIVING:
        raise HTTPException(status_code=400, detail="仅待归档状态工单可执行归档完成")

    is_admin = current_user.role == UserRole.ADMIN.value
    is_assigned_tech = work_order.technician_id == current_user.id or work_order.assignee_id == current_user.id
    if not (is_assigned_tech or is_admin):
        raise HTTPException(status_code=403, detail="仅被指派的维修员或管理员可归档")

    result = _archive_field_check(work_order)
    if not result["passed"]:
        logger.warning(
            f"[Archive] 归档完成被拒绝 #{work_order_id}: missing={result['missing_fields']} by {current_user.real_name}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"归档完成度不足（{result['completeness']:.0%}），缺失字段：{'、'.join(result['missing_fields'])}",
        )

    from_status_enum = work_order.status
    work_order.status = WorkOrderStatus.ARCHIVED
    db.flush()
    _add_progress_log(
        db=db,
        work_order_id=work_order.id,
        from_status=from_status_enum,
        to_status=WorkOrderStatus.ARCHIVED,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        source="WEB",
        remark=f"工单归档完成（完成度 {result['completeness']:.0%}）",
    )
    try:
        _auto_publish_knowledge(work_order, db)
    except Exception as e:
        logger.warning(f"[Archive] 归档时知识收录失败: {e}")
    try:
        _ensure_fault_code_mappings(work_order, db)
    except Exception as e:
        logger.warning(f"[Archive] 归档时故障码映射失败: {e}")

    db.commit()
    db.refresh(work_order)
    logger.info(f"[Archive] 工单归档完成 #{work_order_id}: {work_order.work_order_no} by {current_user.real_name}")
    return {
        "archived": True,
        "work_order_id": work_order.id,
        "work_order_no": work_order.work_order_no,
        "status": WorkOrderStatus.ARCHIVED.value,
        "completeness": result["completeness"],
    }


@router.get("/{work_order_id}/progress", summary="获取工单进度日志")
def get_work_order_progress(
    work_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")

    current_status_val = work_order.status.value if work_order.status else None
    allowed_next = VALID_TRANSITIONS.get(current_status_val, [])

    logs = (
        db.query(WorkOrderProgressLog)
        .filter(WorkOrderProgressLog.work_order_id == work_order_id)
        .order_by(WorkOrderProgressLog.created_at.asc())
        .all()
    )

    log_responses = [
        WorkOrderProgressLogResponse(
            id=l.id,
            work_order_id=l.work_order_id,
            from_status=l.from_status.value if l.from_status else None,
            to_status=l.to_status.value if l.to_status else None,
            operator_id=l.operator_id,
            operator_name=l.operator_name,
            source=l.source,
            remark=l.remark,
            location=l.location,
            attachments=l.attachments,
            created_at=l.created_at,
        )
        for l in logs
    ]

    return {
        "work_order_id": work_order_id,
        "current_status": current_status_val,
        "allowed_next": allowed_next,
        "progress_logs": log_responses,
    }


@router.post("/from-dispatch", response_model=WorkOrderResponse, summary="从派工创建工单(主管)")
def create_work_order_from_dispatch(
    data: WorkOrderDispatchCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail="仅主管或管理员可通过派工创建工单")

    technician = db.query(User).filter(User.id == data.technician_id).first()
    if not technician:
        raise HTTPException(status_code=400, detail="指派的维修员不存在")
    if not technician.is_active:
        raise HTTPException(status_code=400, detail="指派的维修员已停用")
    if technician.role not in (UserRole.TECHNICIAN.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=400, detail="被指派人必须是维修员角色")

    # 在岗校验：查询当天该维修员的排班/请假记录
    today = date.today()
    duty_schedules = (
        db.query(DutySchedule)
        .filter(DutySchedule.date == today, DutySchedule.user_id == data.technician_id)
        .all()
    )
    # 1. 全天请假 → 阻止派工
    for ds in duty_schedules:
        if ds.schedule_type == 'LEAVE' and ds.shift == 'ALL_DAY':
            raise HTTPException(status_code=400, detail="该维修员今日全天请假，无法派工")
    # 2. 当前时段请假 → 阻止派工
    current_shift = _get_current_shift()
    for ds in duty_schedules:
        if ds.schedule_type == 'LEAVE' and ds.shift == current_shift:
            raise HTTPException(
                status_code=400,
                detail=f"该维修员当前时段请假（{current_shift}），无法派工",
            )
    # 3. 无任何排班记录 → 仅警告，允许临时派工
    if not duty_schedules:
        logger.warning(
            f"[WorkOrder] 维修员 #{data.technician_id} 今日无排班记录，允许临时派工"
        )

    today_str = date.today().strftime("%Y%m%d")
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

    work_order = WorkOrder(
        work_order_no=work_order_no,
        device_id=data.device_id,
        device_code=data.device_code,
        fault_code=data.fault_code,
        fault_description=data.fault_description,
        fault_category=data.fault_category,
        fault_phenomenon_type=data.fault_phenomenon_type,
        fault_phenomenon=data.fault_phenomenon,
        fault_media=data.fault_media,
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

    _add_progress_log(
        db=db,
        work_order_id=work_order.id,
        from_status=WorkOrderStatus.DRAFT,
        to_status=WorkOrderStatus.ASSIGNED,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        source="WEB",
        remark=f"主管派工创建工单，指派给 {technician.real_name}",
    )

    _update_workload(db, data.technician_id, +1)

    # ===== 系统站内通知 =====
    device_desc = data.device_code or (f"设备#{data.device_id}" if data.device_id else "未指定设备")
    try:
        from app.api.notifications import create_notification
        create_notification(
            db,
            user_id=data.technician_id,
            type="work_order",
            title=f"新工单派工通知",
            content=f"工单 {work_order_no} 已派发给您，设备：{device_desc}，故障：{(data.fault_description or '')[:60]}",
            work_order_id=work_order.id,
        )
        logger.info(f"[Notification] 站内通知已写入: 工单{work_order_no} → 维修员#{data.technician_id}")
    except Exception as e:
        logger.warning(f"[Notification] 站内通知写入失败（不影响工单创建）: {e}")

    # ===== 钉钉通知（异步）：发送带进度确认按钮的互动卡片 =====
    def _send_dingtalk_dispatch(technician_userid, wo, sup_name):
        try:
            from app.core.dingtalk_wo_card import send_progress_card
            from app.core.config import settings
            public_url = getattr(settings, "SERVER_PUBLIC_URL", "") or ""
            send_progress_card(
                technician_userid,
                wo,
                supervisor_name=sup_name,
                public_url=public_url,
            )
        except Exception as e:
            logger.warning(f"[DingTalk] 派工进度卡片发送失败（不影响工单创建）: {e}")

    background_tasks.add_task(
        _send_dingtalk_dispatch,
        technician.dingtalk_userid or "",
        work_order,
        current_user.real_name,
    )

    db.commit()
    db.refresh(work_order)
    logger.info(f"[WorkOrder] 主管派工创建 {work_order_no} → 技术员 #{data.technician_id}({technician.real_name})")
    return _build_work_order_response(work_order, db)


def _build_work_order_response(work_order: WorkOrder, db: Session) -> WorkOrderResponse:
    resp = WorkOrderResponse.model_validate(work_order)
    if work_order.created_by:
        creator = db.query(User).filter(User.id == work_order.created_by).first()
        resp.created_by_employee_id = creator.employee_id if creator else None
    if work_order.technician_id:
        tech = db.query(User).filter(User.id == work_order.technician_id).first()
        resp.technician_name = tech.real_name if tech else None
    if work_order.progress_logs:
        resp.progress_logs = [
            WorkOrderProgressLogResponse(
                id=l.id,
                work_order_id=l.work_order_id,
                from_status=l.from_status.value if l.from_status else None,
                to_status=l.to_status.value if l.to_status else None,
                operator_id=l.operator_id,
                operator_name=l.operator_name,
                source=l.source,
                remark=l.remark,
                location=l.location,
                attachments=l.attachments,
                created_at=l.created_at,
            )
            for l in work_order.progress_logs
        ]
    return resp
