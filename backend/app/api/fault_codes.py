"""故障码映射表 API - 查询 + 手动新增（自动生成故障码 + 重复检测）"""
from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Optional, List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.fault_code import FaultCodeMapping
from app.models.user import User

router = APIRouter(prefix="/fault-codes", tags=["故障码映射"])

# ==================== 请求/响应模型 ====================

class FaultCodeCreateRequest(BaseModel):
    fault_description: str = Field(..., min_length=2, max_length=500, description="故障描述")
    device_type: Optional[str] = Field(None, description="设备类型，用于自动匹配前缀")

class FaultCodeCreateResponse(BaseModel):
    id: int
    fault_code: str
    fault_description: str
    device_type: str = ""
    source: str = "manual"
    is_new: bool = True
    duplicate_hint: str = ""

# ==================== 设备类型 -> 编码前缀映射 ====================

DEVICE_TYPE_PREFIX = {
    "注塑机": "10", "数控机床": "20", "液压系统": "30",
    "传送带": "40", "空压机": "50", "变压器": "60",
    "电机": "70", "锅炉": "80", "制冷系统": "90",
    "机器人": "11", "PLC系统": "21", "传感器": "31",
    "传感器/仪表": "31", "电气系统": "41",
}

DEFAULT_PREFIX = "99"  # 未知设备类型默认前缀


# ==================== API 端点 ====================

def _to_dict(item) -> dict:
    return {
        "id": item.id,
        "fault_code": item.fault_code,
        "fault_description": item.fault_description,
        "device_type": item.device_type or "",
        "source": item.source or "system",
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/", summary="查询故障码列表")
def list_fault_codes(
    keyword: Optional[str] = Query(None, description="搜索关键词（匹配故障码或故障描述）"),
    device_type: Optional[str] = Query(None, description="设备类型筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查询故障码映射表，支持双向模糊搜索"""
    query = db.query(FaultCodeMapping)

    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(
            or_(
                FaultCodeMapping.fault_code.like(kw),
                FaultCodeMapping.fault_description.like(kw),
            )
        )

    if device_type:
        query = query.filter(FaultCodeMapping.device_type == device_type)

    total = query.count()
    items = query.order_by(FaultCodeMapping.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {"total": total, "items": [_to_dict(item) for item in items]}


@router.get("/device-types", summary="获取所有不重复的设备类型")
def get_device_types(db: Session = Depends(get_db)):
    """返回故障码表中所有不重复的设备类型列表，供前端下拉筛选使用"""
    results = db.query(FaultCodeMapping.device_type).filter(
        FaultCodeMapping.device_type.isnot(None),
        FaultCodeMapping.device_type != "",
    ).distinct().all()
    types = sorted([r[0] for r in results if r[0]])
    return {"device_types": types}


@router.get("/{mapping_id}", summary="查看故障码详情")
def get_fault_code(mapping_id: int, db: Session = Depends(get_db)):
    """查看单条故障码映射"""
    item = db.query(FaultCodeMapping).filter(FaultCodeMapping.id == mapping_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="故障码不存在")
    return _to_dict(item)


@router.post("/create", summary="新增故障码（自动生成 + 重复检测）")
def create_fault_code(req: FaultCodeCreateRequest, db: Session = Depends(get_db)):
    """
    维修员仅填写故障描述，系统自动完成：
    1. 重复检测 → 若描述相似度≈90%则返回已有码，不重复创建
    2. 根据设备类型分配编码前缀
    3. 自动生成下一个可用序号（4位补齐）
    4. 收录到故障码映射表
    """
    desc = req.fault_description.strip()
    device_type = req.device_type or ""

    # 1. 重复检测：搜索已有故障码中描述相似的内容
    #    先精确匹配，再按关键词模糊匹配
    exact_match = db.query(FaultCodeMapping).filter(
        FaultCodeMapping.fault_description == desc
    ).first()
    if exact_match:
        return FaultCodeCreateResponse(
            id=exact_match.id,
            fault_code=exact_match.fault_code,
            fault_description=exact_match.fault_description,
            device_type=exact_match.device_type or "",
            source=exact_match.source or "system",
            is_new=False,
            duplicate_hint=f"已存在相同的故障描述，对应故障码: {exact_match.fault_code}",
        )

    # 关键词去重：取描述中的核心关键词（过滤常见词）
    stop_words = {"的", "了", "在", "有", "和", "是", "不", "与", "时", "后", "中", "上", "下", "出现", "报警", "异常", "故障"}
    keywords = [w for w in desc if len(w) >= 2 and w not in stop_words]
    if keywords:
        fuzzy_query = db.query(FaultCodeMapping)
        conditions = []
        for kw in keywords[:5]:
            conditions.append(FaultCodeMapping.fault_description.like(f"%{kw}%"))
        fuzzy_results = fuzzy_query.filter(or_(*conditions)).all()

        # 如果匹配到超过 60% 的关键词，视为重复
        if fuzzy_results:
            best_match = fuzzy_results[0]
            match_kw_count = sum(1 for kw in keywords if kw in best_match.fault_description)
            if len(keywords) > 0 and match_kw_count / len(keywords) >= 0.6:
                return FaultCodeCreateResponse(
                    id=best_match.id,
                    fault_code=best_match.fault_code,
                    fault_description=best_match.fault_description,
                    device_type=best_match.device_type or "",
                    source=best_match.source or "system",
                    is_new=False,
                    duplicate_hint=f"检测到相似故障描述，对应故障码: {best_match.fault_code}",
                )

    # 2. 确定前缀
    prefix = "99"
    for dt, pfx in DEVICE_TYPE_PREFIX.items():
        if device_type and dt in device_type:
            prefix = pfx
            break
    if device_type and prefix == DEFAULT_PREFIX:
        # 尝试匹配设备类型中的关键词
        for dt, pfx in DEVICE_TYPE_PREFIX.items():
            if any(kw in device_type for kw in dt.split("/")):
                prefix = pfx
                break

    # 3. 自动生成下一个编码
    existing = db.query(FaultCodeMapping).filter(
        FaultCodeMapping.fault_code.like(f"{prefix}%"),
        func.char_length(FaultCodeMapping.fault_code) == 6,
    ).order_by(FaultCodeMapping.fault_code.desc()).first()

    if existing:
        try:
            next_seq = int(existing.fault_code[2:]) + 1
        except ValueError:
            next_seq = 1
    else:
        next_seq = 1

    new_code = f"{prefix}{next_seq:04d}"

    # 确保不重复（理论上不会，但以防万一）
    while db.query(FaultCodeMapping).filter(FaultCodeMapping.fault_code == new_code).first():
        next_seq += 1
        new_code = f"{prefix}{next_seq:04d}"

    # 4. 创建
    mapping = FaultCodeMapping(
        fault_code=new_code,
        fault_description=desc,
        device_type=device_type,
        source="manual",
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    logger.info(f"[FaultCode] 手动新增故障码: {new_code} → {desc[:50]}")
    return FaultCodeCreateResponse(
        id=mapping.id,
        fault_code=mapping.fault_code,
        fault_description=mapping.fault_description,
        device_type=mapping.device_type or "",
        source="manual",
        is_new=True,
        duplicate_hint="",
    )


# ==================== 内部工具函数 ====================

def ensure_fault_code_mapping(
    db: Session,
    fault_code: str,
    fault_description: str,
    device_type: str = "",
    source: str = "system",
) -> Optional[FaultCodeMapping]:
    """
    确保故障码已收录到映射表。
    如果已存在相同故障码但描述不同 → 不覆盖（一一对应原则）
    如果不存在 → 新建
    """
    if not fault_code or not fault_description:
        return None

    existing = db.query(FaultCodeMapping).filter(
        FaultCodeMapping.fault_code == fault_code
    ).first()

    if existing:
        # 已存在，不覆盖（一一对应，不可修改）
        return existing

    mapping = FaultCodeMapping(
        fault_code=fault_code,
        fault_description=fault_description,
        device_type=device_type,
        source=source,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    logger.info(f"[FaultCode] 新故障码收录: {fault_code} → {fault_description[:50]}")
    return mapping
