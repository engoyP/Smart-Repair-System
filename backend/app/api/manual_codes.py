"""设备手册错误码管理 API

管理从设备说明书导入的"错误码 → 故障诊断"条目（manual_code_entries 表 + log_code 集合）。
数据边界：本模块只管理手册条目，工单知识走 knowledge.py。

录入方式：
- POST /parse          LLM 结构化（粘贴手册原文 → entries，只预填不落库）
- POST /               单条新建（ADMIN，PG + Milvus 同步写）
- PUT /{id}            单条更新（ADMIN，PG + Milvus 删旧插新）
- POST /import-json    批量导入（ADMIN，upsert，单条失败不中断）
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.manual_code import ManualCodeEntry
from app.models.user import User, UserRole

router = APIRouter()


# ==================== Pydantic 模型 ====================

class ManualCondition(BaseModel):
    """手册条目的一个情形：可观察信号 → 原因 → 处理步骤"""
    signal: str = ""
    cause: str = ""
    steps: str = ""


class ManualCodeCreate(BaseModel):
    manual_name: str = Field(..., min_length=1, max_length=200, description="手册名称")
    device_type: Optional[str] = Field(None, max_length=100)
    error_code: str = Field(..., min_length=1, max_length=100, description="错误码，如 SV0436")
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, description="错误含义/触发条件")
    message_text: Optional[str] = Field(None, description="屏幕/日志原文")
    severity: Optional[str] = Field(None, description="EX / OH / INFO")
    effect: Optional[str] = Field(None, max_length=50, description="急停 / 停机 / 仅提示")
    related_codes: List[str] = Field(default_factory=list)
    conditions: List[ManualCondition] = Field(default_factory=list)
    chapter: Optional[str] = Field(None, max_length=200)
    page: Optional[str] = Field(None, max_length=50)

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if v not in ("EX", "OH", "INFO"):
            raise ValueError("severity 只能是 EX / OH / INFO")
        return v


class ManualCodeUpdate(BaseModel):
    manual_name: Optional[str] = Field(None, min_length=1, max_length=200)
    device_type: Optional[str] = Field(None, max_length=100)
    error_code: Optional[str] = Field(None, min_length=1, max_length=100)
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = Field(None, min_length=1)
    message_text: Optional[str] = None
    severity: Optional[str] = None
    effect: Optional[str] = Field(None, max_length=50)
    related_codes: Optional[List[str]] = None
    conditions: Optional[List[ManualCondition]] = None
    chapter: Optional[str] = None
    page: Optional[str] = None

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if v not in ("EX", "OH", "INFO"):
            raise ValueError("severity 只能是 EX / OH / INFO")
        return v


class ManualParseRequest(BaseModel):
    manual_text: str = Field(..., min_length=1, max_length=8000, description="手册原文段落")
    manual_name: str = ""
    device_type: str = ""


class ManualImportJsonRequest(BaseModel):
    items: List[ManualCodeCreate] = Field(..., min_length=1, max_length=500)


# ==================== 工具函数 ====================

def _m_to_dict(m: ManualCodeEntry) -> dict:
    return {c.name: getattr(m, c.name) for c in m.__table__.columns}


def _require_admin(current_user: User) -> None:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="仅管理员可维护手册条目")


def _sync_vector(entry: ManualCodeEntry, data: dict) -> str:
    """按当前字段编码并写入/更新 Milvus log_code 集合，返回新 point_id"""
    from app.core.embeddings import encode_text
    from app.core.manual_text import build_manual_embedding_text
    from app.core.vector_store import log_code_store

    vector = encode_text(build_manual_embedding_text(data))
    point_id = log_code_store.insert(
        vector=vector,
        manual_code_id=entry.id,
        error_code=data["error_code"],
        manual_name=data["manual_name"],
        device_type=data.get("device_type"),
        title=data["title"],
        description=data["description"],
        chapter=data.get("chapter") or "",
        page=data.get("page") or "",
    )
    return str(point_id)


def _normalized_field_map(data: BaseModel) -> dict:
    """Pydantic 请求 → 归一化字段 dict（error_code 大写、manual_name 去空白）"""
    from app.core.manual_text import normalize_error_code
    m = data.model_dump(exclude_unset=True, exclude_none=False)
    if "error_code" in m and m["error_code"] is not None:
        m["error_code"] = normalize_error_code(m["error_code"])
    if "manual_name" in m and m["manual_name"] is not None:
        m["manual_name"] = m["manual_name"].strip()
    return m


def _apply_fields(entry: ManualCodeEntry, data: dict) -> None:
    """把字段 dict 应用到 ORM 对象（conditions/related_codes 走 JSONB 整体替换）"""
    for k, v in data.items():
        if hasattr(entry, k):
            setattr(entry, k, v)


def _check_conflict(db: Session, manual_name: str, error_code: str, exclude_id: Optional[int] = None) -> None:
    from app.core.manual_text import normalize_error_code
    q = db.query(ManualCodeEntry).filter(
        ManualCodeEntry.manual_name == manual_name.strip(),
        ManualCodeEntry.error_code == normalize_error_code(error_code),
    )
    if exclude_id is not None:
        q = q.filter(ManualCodeEntry.id != exclude_id)
    if q.first():
        raise HTTPException(status_code=409, detail=f"该手册下错误码 {normalize_error_code(error_code)} 已存在")


# ==================== 查询端点（不变） ====================

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


# ==================== LLM 结构化（预填，不落库） ====================

@router.post("/parse", summary="LLM 结构化手册原文（只预填不落库）")
def parse_manual_text(
    request: ManualParseRequest,
    current_user: User = Depends(get_current_user),
):
    """粘贴设备手册「错误码表」原文 → DeepSeek 提取结构化条目，回填表单人工确认后保存"""
    try:
        from app.agents.manual_structurizer import structurize_manual_text
        return structurize_manual_text(
            request.manual_text,
            manual_name=request.manual_name,
            device_type=request.device_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ManualCodes] LLM 结构化失败: {e}")
        raise HTTPException(status_code=502, detail=f"结构化失败: {e}")


# ==================== 写入端点（ADMIN，PG + Milvus 同步） ====================

@router.post("/", summary="新建手册错误码条目（PG + Milvus 同步）")
def create_manual_code(
    data: ManualCodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    fields = _normalized_field_map(data)
    _check_conflict(db, fields["manual_name"], fields["error_code"])

    entry = ManualCodeEntry(**fields)
    db.add(entry)
    try:
        db.flush()   # 拿到 entry.id 再写向量
        point_id = _sync_vector(entry, fields)
        entry.milvus_id = point_id
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"该手册下错误码 {fields['error_code']} 已存在")
    except Exception as e:
        db.rollback()
        logger.error(f"[ManualCodes] 新建条目失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败（PG 已回滚）: {e}")
    db.refresh(entry)
    logger.info(f"[ManualCodes] 新建手册条目: id={entry.id}, error_code={entry.error_code}, 手册={entry.manual_name}")
    return _m_to_dict(entry)


@router.put("/{manual_code_id}", summary="更新手册错误码条目（PG + Milvus 删旧插新）")
def update_manual_code(
    manual_code_id: int,
    data: ManualCodeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    item = db.query(ManualCodeEntry).filter(ManualCodeEntry.id == manual_code_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="手册条目不存在")

    fields = _normalized_field_map(data)
    new_manual_name = fields.get("manual_name", item.manual_name)
    new_error_code = fields.get("error_code", item.error_code)
    _check_conflict(db, new_manual_name, new_error_code, exclude_id=manual_code_id)

    old_milvus_id = item.milvus_id
    _apply_fields(item, fields)
    try:
        db.flush()
        # 新向量按最新字段编码；Milvus 无 update，删旧点 + 插新点
        merged = _m_to_dict(item)
        new_point_id = _sync_vector(item, merged)
        if old_milvus_id:
            from app.core.vector_store import log_code_store
            log_code_store.delete(old_milvus_id)
        item.milvus_id = new_point_id
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"该手册下错误码 {new_error_code} 已存在")
    except Exception as e:
        db.rollback()
        logger.error(f"[ManualCodes] 更新条目失败 (id={manual_code_id}): {e}")
        raise HTTPException(status_code=500, detail=f"更新失败（PG 已回滚，可用 --resync 重灌向量）: {e}")
    db.refresh(item)
    return _m_to_dict(item)


@router.post("/import-json", summary="JSON 批量导入手册条目（upsert）")
def import_manual_codes_json(
    request: ManualImportJsonRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量 upsert：同 (manual_name, error_code) 更新，否则新建；单条失败不中断整批"""
    _require_admin(current_user)
    from app.core.vector_store import log_code_store

    created, updated, failed = 0, 0, []
    for data in request.items:
        try:
            fields = _normalized_field_map(data)
            existing = db.query(ManualCodeEntry).filter(
                ManualCodeEntry.manual_name == fields["manual_name"],
                ManualCodeEntry.error_code == fields["error_code"],
            ).first()
            if existing:
                old_milvus_id = existing.milvus_id
                _apply_fields(existing, fields)
                db.flush()
                merged = _m_to_dict(existing)
                new_point_id = _sync_vector(existing, merged)
                if old_milvus_id:
                    log_code_store.delete(old_milvus_id)
                existing.milvus_id = new_point_id
                updated += 1
            else:
                entry = ManualCodeEntry(**fields)
                db.add(entry)
                db.flush()
                entry.milvus_id = _sync_vector(entry, fields)
                created += 1
            db.commit()
        except HTTPException:
            db.rollback()
            failed.append({"error_code": data.error_code, "reason": "已存在冲突"})
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning(f"[ManualCodes] 批量导入单条失败 ({data.error_code}): {e}")
            failed.append({"error_code": data.error_code, "reason": str(e)[:200]})

    logger.info(f"[ManualCodes] 批量导入完成: 新建 {created}, 更新 {updated}, 失败 {len(failed)}")
    return {"created": created, "updated": updated, "failed": failed}


# ==================== 删除端点（不变） ====================

@router.delete("/{manual_code_id}", summary="删除手册错误码（PG + Milvus 同步）")
def delete_manual_code(
    manual_code_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除手册条目：同时删除 Milvus log_code 集合中的对应向量"""
    _require_admin(current_user)

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
