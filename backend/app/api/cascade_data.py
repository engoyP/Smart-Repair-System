"""级联分类数据 API — 故障现象 / 根本原因"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.models.fault_phenomenon_category import FaultPhenomenonCategory
from app.models.root_cause_category import RootCauseCategory

router = APIRouter(prefix="/categories/data", tags=["分类数据"])


def _build_tree(items, parent_id=None):
    """将平铺列表转为级联树结构 [{value, label, children}]"""
    tree = []
    for item in items:
        if item.parent_id == parent_id:
            children = _build_tree(items, item.id)
            node = {"value": item.name, "label": item.name}
            if children:
                node["children"] = children
            tree.append(node)
    return tree


# ==================== 故障现象级联数据 ====================

@router.get("/fault-phenomena", summary="故障现象级联选项")
def get_fault_phenomena(
    device_type: Optional[str] = Query(None, description="设备类型筛选"),
    db: Session = Depends(get_db),
):
    """返回故障现象两级级联树，用于前端 el-cascader"""
    query = db.query(FaultPhenomenonCategory)

    if device_type:
        # 返回：通用 + 匹配设备类型的
        query = query.filter(
            (FaultPhenomenonCategory.device_type == None) |
            (FaultPhenomenonCategory.device_type == device_type)
        )

    items = query.order_by(FaultPhenomenonCategory.sort_order, FaultPhenomenonCategory.id).all()
    tree = _build_tree(items)
    return {"data": tree}


# ==================== 根本原因级联数据 ====================

@router.get("/root-causes", summary="根本原因级联选项")
def get_root_causes(db: Session = Depends(get_db)):
    """返回根本原因两级级联树，用于前端 el-cascader"""
    items = db.query(RootCauseCategory).order_by(
        RootCauseCategory.sort_order, RootCauseCategory.id
    ).all()
    tree = _build_tree(items)
    return {"data": tree}
