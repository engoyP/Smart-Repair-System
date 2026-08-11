"""设备手册错误码管理 API

管理从设备说明书导入的"错误码 → 故障诊断"条目（manual_code_entries 表 + log_code 集合）。
数据边界：本模块只管理手册条目，工单知识走 knowledge.py。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.manual_code import ManualCodeEntry
from app.models.user import User, UserRole

router = APIRouter()


def _m_to_dict(m: ManualCodeEntry) -> dict:
    return {c.name: getattr(m, c.name) for c in m.__table__.columns}


@router.get("/", summary="获取设备手册错误码列表")
def list_manual_codes(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: Optional[str] = None,
    device_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手册条目列表（按错误码/标题/手册名搜索，可按设备类型筛选，分页）"""
    query = db.query(ManualCodeEntry)
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(
            ManualCodeEntry.error_code.ilike(kw)
            | ManualCodeEntry.title.ilike(kw)
            | ManualCodeEntry.manual_name.ilike(kw)
        )
    if device_type:
        query = query.filter(ManualCodeEntry.device_type == device_type)
    total = query.count()
    items = query.order_by(ManualCodeEntry.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_m_to_dict(m) for m in items], "page": page, "page_size": page_size}


@router.get("/{manual_code_id}", summary="获取手册错误码详情")
def get_manual_code(manual_code_id: int, db: Session = Depends(get_db)):
    item = db.query(ManualCodeEntry).filter(ManualCodeEntry.id == manual_code_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="手册条目不存在")
    return _m_to_dict(item)


@router.delete("/{manual_code_id}", summary="删除手册错误码（PG + Milvus 同步）")
def delete_manual_code(
    manual_code_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除手册条目：同时删除 Milvus log_code 集合中的对应向量"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="仅管理员可删除手册条目")

    item = db.query(ManualCodeEntry).filter(ManualCodeEntry.id == manual_code_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="手册条目不存在")

    # 1. 删 Milvus 向量（存在 milvus_id 才删）
    if item.milvus_id:
        try:
            from app.core.vector_store import log_code_store
            log_code_store.delete(item.milvus_id)
        except Exception as e:
            logger.error(f"删除 log_code 向量失败 (milvus_id={item.milvus_id}): {e}")
            raise HTTPException(status_code=500, detail=f"删除向量失败: {str(e)}")

    # 2. 删 PG 记录
    db.delete(item)
    db.commit()
    logger.info(f"[ManualCodes] 删除手册条目: id={manual_code_id}, error_code={item.error_code}, 手册={item.manual_name}")
    return {"message": "删除成功", "id": manual_code_id}
