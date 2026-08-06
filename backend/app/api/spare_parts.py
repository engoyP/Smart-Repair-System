from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, List
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.notification import notification_service
from app.core.cache_service import cache_service
from app.models.spare_part import SparePart
from app.models.user import User
from app.schemas import SparePartCreate, SparePartUpdate, SparePartResponse, PaginatedResponse

router = APIRouter()


def _sp_to_dict(s: SparePart) -> dict:
    return {c.name: getattr(s, c.name) for c in s.__table__.columns}


# ==================== 进货单导入 Schema ====================
class PurchaseItem(BaseModel):
    part_code: str = Field(..., max_length=50)
    part_name: Optional[str] = None
    specification: Optional[str] = None
    unit: Optional[str] = "个"
    quantity: int = Field(..., gt=0, description="进货数量")
    unit_price: Optional[float] = 0.0
    device_type: Optional[str] = None
    location: Optional[str] = None
    supplier: Optional[str] = None
    safety_stock: Optional[int] = 0


class PurchaseImportRequest(BaseModel):
    items: List[PurchaseItem] = Field(..., min_length=1, max_length=200)


class PurchaseImportResult(BaseModel):
    total: int
    created: int = 0
    updated: int = 0
    skipped: int = 0
    details: List[dict] = []


# ==================== CRUD ====================

@router.get("/", response_model=PaginatedResponse[SparePartResponse], summary="获取备件列表")
def list_spare_parts(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    device_type: Optional[str] = None,
    keyword: Optional[str] = None,
    stock_status: Optional[str] = Query(None, description="low_stock / out_of_stock"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SparePart)
    if device_type:
        query = query.filter(SparePart.device_type == device_type)
    if keyword:
        query = query.filter(
            SparePart.part_name.ilike(f"%{keyword}%")
            | SparePart.part_code.ilike(f"%{keyword}%")
            | SparePart.specification.ilike(f"%{keyword}%")
        )
    if stock_status == "low_stock":
        query = query.filter(
            SparePart.stock_quantity > 0,
            SparePart.stock_quantity <= SparePart.safety_stock
        )
    elif stock_status == "out_of_stock":
        query = query.filter(SparePart.stock_quantity <= 0)

    total = query.count()
    items = query.order_by(SparePart.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_sp_to_dict(s) for s in items], "page": page, "page_size": page_size}


@router.get("/alerts", summary="库存预警（带缓存）")
def get_stock_alerts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取低库存和缺货预警数据（缓存 30 秒）"""
    cache_key = "stock_alerts:all"
    cached = cache_service.get(cache_key)
    if cached:
        return cached

    low_stock = db.query(SparePart).filter(
        SparePart.stock_quantity > 0,
        SparePart.stock_quantity <= SparePart.safety_stock
    ).all()

    out_of_stock = db.query(SparePart).filter(
        SparePart.stock_quantity <= 0
    ).all()

    result = {
        "low_stock_count": len(low_stock),
        "out_of_stock_count": len(out_of_stock),
        "alert_count": len(low_stock) + len(out_of_stock),
        "low_stock_items": [_sp_to_dict(s) for s in low_stock],
        "out_of_stock_items": [_sp_to_dict(s) for s in out_of_stock],
    }
    cache_service.set(cache_key, result, ttl=30)
    return result


@router.post("/check-alerts", summary="手动触发库存预警检查")
def check_stock_alerts(db: Session = Depends(get_db)):
    """
    手动触发库存预警检查，发送钉钉通知
    返回预警结果
    """
    from app.core.stock_alert import check_and_notify_stock_alerts
    result = check_and_notify_stock_alerts(db)
    return result


@router.get("/{part_id}", response_model=SparePartResponse, summary="获取备件详情（带缓存）")
def get_spare_part(part_id: int, db: Session = Depends(get_db)):
    cache_key = f"spare_part:{part_id}"
    cached = cache_service.get(cache_key)
    if cached:
        return cached

    part = db.query(SparePart).filter(SparePart.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="备件不存在")

    result = _sp_to_dict(part)
    cache_service.set(cache_key, result, ttl=300)
    return result


@router.post("/", response_model=SparePartResponse, summary="创建备件")
def create_spare_part(data: SparePartCreate, db: Session = Depends(get_db)):
    existing = db.query(SparePart).filter(SparePart.part_code == data.part_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="备件编码已存在")
    part = SparePart(**data.model_dump())
    db.add(part)
    db.commit()
    db.refresh(part)
    cache_service.invalidate_pattern("stock_alerts:*")
    return part


@router.put("/{part_id}", response_model=SparePartResponse, summary="更新备件")
def update_spare_part(part_id: int, data: SparePartUpdate, db: Session = Depends(get_db)):
    part = db.query(SparePart).filter(SparePart.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="备件不存在")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(part, key, val)
    db.commit()
    db.refresh(part)
    cache_service.delete(f"spare_part:{part_id}")
    cache_service.invalidate_pattern("stock_alerts:*")
    return part


@router.delete("/{part_id}", summary="删除备件")
def delete_spare_part(part_id: int, db: Session = Depends(get_db)):
    part = db.query(SparePart).filter(SparePart.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="备件不存在")
    db.delete(part)
    db.commit()
    cache_service.delete(f"spare_part:{part_id}")
    cache_service.invalidate_pattern("stock_alerts:*")
    return {"message": "备件已删除"}


# ==================== 进货单批量导入 ====================

@router.post("/import", response_model=PurchaseImportResult, summary="进货单批量导入")
def import_purchase_orders(req: PurchaseImportRequest, db: Session = Depends(get_db)):
    """
    批量导入备件：
    - 新备件（编码不存在）→ 自动创建
    - 已有备件（编码存在）→ 累加库存数量，更新单价和供应商
    """
    result = PurchaseImportResult(total=len(req.items))
    details = []

    for item in req.items:
        existing = db.query(SparePart).filter(SparePart.part_code == item.part_code).first()

        if existing:
            # 已有备件：累加库存
            existing.stock_quantity += item.quantity
            if item.unit_price and item.unit_price > 0:
                existing.unit_price = item.unit_price
            if item.supplier:
                existing.supplier = item.supplier
            if item.location:
                existing.location = item.location
            if item.safety_stock > 0:
                existing.safety_stock = item.safety_stock
            if item.part_name and not existing.part_name:
                existing.part_name = item.part_name
            if item.specification and not existing.specification:
                existing.specification = item.specification
            result.updated += 1
            details.append({
                "part_code": item.part_code,
                "action": "updated",
                "quantity_added": item.quantity,
                "new_stock": existing.stock_quantity,
            })
        else:
            # 新备件：创建
            part = SparePart(
                part_code=item.part_code,
                part_name=item.part_name or item.part_code,
                specification=item.specification,
                unit=item.unit or "个",
                stock_quantity=item.quantity,
                safety_stock=item.safety_stock or 0,
                unit_price=item.unit_price or 0,
                device_type=item.device_type,
                location=item.location,
                supplier=item.supplier,
            )
            db.add(part)
            result.created += 1
            details.append({
                "part_code": item.part_code,
                "action": "created",
                "quantity": item.quantity,
            })

    db.commit()
    cache_service.invalidate_pattern("stock_alerts:*")
    logger.info(f"[SpareParts] 进货单导入完成: 共{result.total}项, 新建{result.created}, 更新{result.updated}")
    result.details = details
    return result
