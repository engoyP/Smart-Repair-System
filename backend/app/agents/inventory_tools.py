"""query_inventory - 库存查询工具

根据设备类型、故障码或关键词查询备件库存，用于工单录入时自动关联备件。
"""
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from app.models.spare_part import SparePart


def query_inventory(
    db: Session,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 10,
) -> Dict:
    """
    查询备件库存

    Args:
        db: 数据库会话
        device_type: 设备类型过滤
        fault_code: 故障码（按设备类型模糊匹配）
        keyword: 关键词搜索（备件名称/编码）
        limit: 返回数量上限

    Returns:
        {
            "total": int,
            "items": [...],
            "low_stock_items": [...],   # 库存低于安全库存的备件
            "out_of_stock_items": [...], # 已缺货的备件
        }
    """
    query = db.query(SparePart)

    # 按设备类型过滤
    if device_type:
        query = query.filter(SparePart.device_type == device_type)

    # 按关键词搜索
    if keyword:
        query = query.filter(
            SparePart.part_name.ilike(f"%{keyword}%")
            | SparePart.part_code.ilike(f"%{keyword}%")
            | SparePart.specification.ilike(f"%{keyword}%")
        )

    # 如果只指定了 fault_code，尝试从故障码中提取设备类型信息进行匹配
    if fault_code and not device_type and not keyword:
        # 取故障码前缀作为设备类型线索
        code_prefix = fault_code.split("_")[0] if "_" in fault_code else fault_code[:4]
        query = query.filter(SparePart.device_type.ilike(f"%{code_prefix}%"))

    items = query.order_by(SparePart.id.desc()).limit(limit).all()

    # 转换结果
    result_items = []
    low_stock_items = []
    out_of_stock_items = []

    for sp in items:
        item = {
            "id": sp.id,
            "part_code": sp.part_code,
            "part_name": sp.part_name,
            "specification": sp.specification,
            "unit": sp.unit,
            "stock_quantity": sp.stock_quantity,
            "safety_stock": sp.safety_stock,
            "unit_price": sp.unit_price,
            "device_type": sp.device_type,
            "location": sp.location,
            "supplier": sp.supplier,
        }
        result_items.append(item)

        if sp.stock_quantity <= 0:
            out_of_stock_items.append(item)
        elif sp.stock_quantity <= sp.safety_stock:
            low_stock_items.append(item)

    return {
        "total": len(result_items),
        "items": result_items,
        "low_stock_items": low_stock_items,
        "out_of_stock_items": out_of_stock_items,
    }
