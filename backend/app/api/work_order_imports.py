"""历史工单 PDF 导入 API

流程：
1. 上传 PDF 文件 → 保存到 uploads/pdf_import → 建批次 → 逐份跑 LangGraph 导入流水线
   （解析→DeepSeek 结构化抽取→校验→保存为待确认记录 WorkOrderImportItem）
2. 后台人工核对/修改/确认
3. 确认后才写入 work_orders 并收录知识库（去重到知识库在人工确认之后）
"""
import os
import re
import uuid
from datetime import date, datetime, time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from app.core.database import get_db, SessionLocal
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.work_order_import import WorkOrderImportBatch, WorkOrderImportItem
from app.models.work_order import WorkOrder
from app.models.device import Device
from app.agents.work_order_importer import invoke_import_pdf

router = APIRouter(tags=["历史工单导入"])

IMPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploads", "pdf_import",
)

# 历史工单由维修员（TECHNICIAN）负责核对确认，管理员/主管保留权限
_MANAGE_ROLES = {UserRole.ADMIN.value, UserRole.SUPERVISOR.value, UserRole.TECHNICIAN.value, "MANAGER"}


def _require_manage(current_user: User):
    if current_user.role not in _MANAGE_ROLES:
        raise HTTPException(status_code=403, detail="仅管理员/主管/维修员可执行历史工单导入")


# ============================================================
# 上传并跑 LangGraph 流水线
# ============================================================
class UploadResult(BaseModel):
    file_name: str
    status: str          # PENDING / ERROR
    item_id: Optional[int] = None
    message: str = ""


@router.post("/upload", summary="上传历史工单 PDF 并批量抽取（LangGraph 流水线）")
async def upload_pdf_workorders(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_manage(current_user)
    if not files:
        raise HTTPException(status_code=400, detail="请选择 PDF 文件")
    if len(files) > 50:
        raise HTTPException(status_code=400, detail="单次最多上传 50 份 PDF")

    os.makedirs(IMPORT_DIR, exist_ok=True)

    # 1. 建批次
    batch = WorkOrderImportBatch(
        batch_no=f"IMPORT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}",
        status="PROCESSING",
        file_count=len(files),
        created_by=current_user.id,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    results: List[dict] = []
    saved_paths = []
    try:
        # 2. 保存文件并逐份跑流水线
        for f in files:
            ext = os.path.splitext(f.filename or "")[1].lower()
            if ext != ".pdf":
                results.append({"file_name": f.filename or "", "status": "ERROR",
                                "message": f"不支持的文件类型: {ext or '未知'}"})
                continue
            unique_name = f"{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:12]}.pdf"
            file_path = os.path.join(IMPORT_DIR, unique_name)
            content = await f.read()
            with open(file_path, "wb") as fp:
                fp.write(content)
            saved_paths.append(file_path)

            try:
                r = invoke_import_pdf(file_path, f.filename or unique_name, batch.id)
            except Exception as e:
                logger.exception(f"[WOImport] 处理异常: {f.filename}")
                r = {"file_name": f.filename or unique_name, "status": "ERROR",
                     "message": f"处理异常: {e}"}
            results.append(r)

        # 3. 汇总批次
        pending = sum(1 for r in results if r.get("status") == "PENDING")
        failed = sum(1 for r in results if r.get("status") == "ERROR")
        batch.total_count = pending
        batch.failed_count = failed
        batch.status = "DONE" if failed == 0 else "PARTIAL"
        batch.report = results
        db.commit()
    except Exception as e:
        logger.exception("[WOImport] 上传批次处理失败")
        batch.status = "PARTIAL"
        batch.report = results
        db.commit()
        raise HTTPException(status_code=500, detail=f"批量处理失败: {e}")

    return {
        "batch_id": batch.id,
        "batch_no": batch.batch_no,
        "status": batch.status,
        "total_pending": batch.total_count,
        "failed": batch.failed_count,
        "results": results,
    }


# ============================================================
# 批次 / 待确认清单
# ============================================================
@router.get("/batches", summary="导入批次列表")
def list_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_manage(current_user)
    total = db.query(WorkOrderImportBatch).count()
    items = (
        db.query(WorkOrderImportBatch)
        .order_by(WorkOrderImportBatch.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [{
            "id": b.id,
            "batch_no": b.batch_no,
            "status": b.status,
            "file_count": b.file_count,
            "total_count": b.total_count,
            "success_count": b.success_count,
            "failed_count": b.failed_count,
            "created_at": b.created_at,
            "report": b.report,
        } for b in items],
        "page": page,
        "page_size": page_size,
    }


@router.get("/items", summary="待确认/已处理清单")
def list_items(
    batch_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="PENDING/CONFIRMED/REJECTED/ERROR"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_manage(current_user)
    query = db.query(WorkOrderImportItem)
    if batch_id:
        query = query.filter(WorkOrderImportItem.batch_id == batch_id)
    if status:
        query = query.filter(WorkOrderImportItem.status == status)
    total = query.count()
    items = (
        query.order_by(WorkOrderImportItem.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [{
            "id": it.id,
            "batch_id": it.batch_id,
            "file_name": it.file_name,
            "status": it.status,
            "error_message": it.error_message,
            "extracted_data": it.extracted_data,
            "validate_warnings": it.validate_warnings or [],
            "work_order_id": it.work_order_id,
            "created_at": it.created_at,
            "confirmed_at": it.confirmed_at,
        } for it in items],
        "page": page,
        "page_size": page_size,
    }


# ============================================================
# 人工编辑 / 确认 / 拒绝
# ============================================================
class ItemUpdate(BaseModel):
    extracted_data: dict


@router.put("/items/{item_id}", summary="人工修改抽取结果")
def update_item(
    item_id: int,
    data: ItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_manage(current_user)
    item = db.query(WorkOrderImportItem).filter(WorkOrderImportItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="记录不存在")
    if item.status == "CONFIRMED":
        raise HTTPException(status_code=400, detail="已确认入库的记录不可再修改")
    item.extracted_data = data.extracted_data
    db.commit()
    return {"message": "已保存修改"}


def _parse_dt(value) -> Optional[datetime]:
    """解析 YYYY-MM-DD HH:MM / YYYY-MM-DD 字符串"""
    if not value:
        return None
    s = str(value).strip()
    try:
        if "T" in s:
            return datetime.fromisoformat(s)
        if re.match(r"\d{4}-\d{2}-\d{2}$", s):
            return datetime.combine(datetime.strptime(s, "%Y-%m-%d").date(), time.min)
        return datetime.strptime(s, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None


def _gen_wo_no(db: Session) -> str:
    today_str = date.today().strftime("%Y%m%d")
    prefix = f"WO-{today_str}-"
    latest = (
        db.query(WorkOrder)
        .filter(WorkOrder.work_order_no.like(f"{prefix}%"))
        .order_by(WorkOrder.work_order_no.desc())
        .first()
    )
    seq = 1
    if latest and latest.work_order_no:
        try:
            seq = int(latest.work_order_no.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:03d}"


def _resolve_user(db: Session, name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    u = db.query(User).filter(User.real_name == str(name).strip()).first()
    return u.id if u else None


@router.post("/items/{item_id}/confirm", summary="确认入库（写入工单 + 收录知识库）")
def confirm_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_manage(current_user)
    item = db.query(WorkOrderImportItem).filter(WorkOrderImportItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="记录不存在")
    if item.status == "CONFIRMED":
        return {"message": "该记录已确认入库", "work_order_id": item.work_order_id}
    data = item.extracted_data or {}

    # 工单号：已有则校验唯一，否则自动生成
    wo_no = str(data.get("work_order_no") or "").strip()
    if wo_no:
        if db.query(WorkOrder).filter(WorkOrder.work_order_no == wo_no).first():
            raise HTTPException(status_code=400, detail=f"工单号 {wo_no} 已存在，请修改后重试")
    else:
        wo_no = _gen_wo_no(db)

    fault_description = str(data.get("fault_description") or "").strip()
    if not fault_description:
        raise HTTPException(status_code=400, detail="故障描述不能为空")

    # 设备 / 用户
    device_id = data.get("device_id")
    if not device_id and data.get("device_code"):
        dev = db.query(Device).filter(Device.device_code == str(data["device_code"])).first()
        device_id = dev.id if dev else None
    technician_id = data.get("technician_id") or _resolve_user(db, data.get("technician_name"))
    reporter_id = data.get("reporter_id") or _resolve_user(db, data.get("reporter_name"))

    wo = WorkOrder(
        work_order_no=wo_no,
        device_id=device_id,
        device_code=str(data.get("device_code") or "") or None,
        fault_code=str(data.get("fault_code") or ""),
        fault_description=fault_description,
        fault_category=data.get("fault_category") or None,
        fault_phenomenon_type=data.get("fault_phenomenon_type") or None,
        fault_phenomenon=data.get("fault_phenomenon") or None,
        root_cause_category=data.get("root_cause_category") or None,
        root_cause=data.get("root_cause") or None,
        solution_steps=data.get("solution_steps") or None,
        repair_result=data.get("repair_result") or None,
        work_hours=float(data["work_hours"]) if data.get("work_hours") else None,
        used_parts=data.get("used_parts") or None,
        priority=data.get("priority") or "MEDIUM",
        location=data.get("location") or None,
        start_time=_parse_dt(data.get("start_time")),
        end_time=_parse_dt(data.get("end_time")),
        technician_id=technician_id,
        reporter_id=reporter_id,
        tags=data.get("tags") or None,
        status="ARCHIVED",  # 历史工单已完工，直接归档
        created_by=current_user.id,
    )
    db.add(wo)
    db.flush()

    # 收录知识库（人工确认之后才去重收录）
    knowledge_synced = False
    try:
        from app.api.work_orders import _auto_publish_knowledge
        knowledge_synced = bool(_auto_publish_knowledge(wo, db))
    except Exception as e:
        logger.warning(f"[WOImport] 知识库收录失败: {e}")

    db.commit()
    db.refresh(wo)

    item.status = "CONFIRMED"
    item.work_order_id = wo.id
    item.confirmed_at = datetime.now()
    item.confirmed_by = current_user.id
    batch = db.query(WorkOrderImportBatch).filter(WorkOrderImportBatch.id == item.batch_id).first()
    if batch:
        batch.success_count = (batch.success_count or 0) + 1
    db.commit()

    logger.info(f"[WOImport] 确认入库: item={item.id} wo={wo_no} knowledge={knowledge_synced}")
    return {
        "message": "已确认入库并收录知识库" if knowledge_synced else "已确认入库（知识库跳过/提取失败）",
        "work_order_id": wo.id,
        "work_order_no": wo_no,
        "knowledge_synced": knowledge_synced,
    }


@router.post("/items/{item_id}/reject", summary="拒绝该条记录")
def reject_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_manage(current_user)
    item = db.query(WorkOrderImportItem).filter(WorkOrderImportItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="记录不存在")
    if item.status == "CONFIRMED":
        raise HTTPException(status_code=400, detail="已确认入库的记录不可拒绝")
    item.status = "REJECTED"
    db.commit()
    return {"message": "已拒绝该记录"}
