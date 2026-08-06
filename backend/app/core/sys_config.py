"""系统配置 K/V 读写工具（基于 SysConfig 表）

最小可用实现：带缓存，支持 int/float/bool/str 四种类型自动转换，
missing 时返回默认值（不抛异常，避免升级表结构时服务启动失败）。
"""
import threading
from typing import Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from loguru import logger


_CACHE_TTL_SECS = 60

_lock = threading.Lock()
_cache: dict = {}   # {key: (value, fetched_at)}


def _from_db(db: Session, key: str) -> Optional[str]:
    try:
        from app.models.sys_config import SysConfig
        row = db.query(SysConfig).filter(SysConfig.key == key).first()
        return row.value if row else None
    except Exception as e:
        # 表不存在/不可用 → None，走 default 兜底
        logger.debug(f"[SysConfig] 读 {key} 异常: {e}")
        return None


def _coerce(raw: Optional[str], default: Any, cast=None) -> Any:
    if raw is None:
        return default
    if cast is not None:
        try:
            return cast(raw)
        except (ValueError, TypeError):
            return default
    # auto infer from default type
    if isinstance(default, bool):
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off", ""):
            return False
        return default
    if isinstance(default, int):
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except (ValueError, TypeError):
            return default
    return str(raw)


def get(db: Session, key: str, default: Any = None, use_cache: bool = True) -> Any:
    """读配置；default 的类型决定了返回类型（自动转换）"""
    now = datetime.utcnow()
    if use_cache:
        with _lock:
            entry = _cache.get(key)
            if entry and (now - entry[1]) < timedelta(seconds=_CACHE_TTL_SECS):
                return _coerce(entry[0], default)
    raw = _from_db(db, key)
    value = _coerce(raw, default)
    # only cache when DB returns non-None, default-value hits still go to DB next time for safety
    if raw is not None and use_cache:
        with _lock:
            _cache[key] = (raw, now)
    return value


def set_value(db: Session, key: str, value: Any, description: Optional[str] = None) -> None:
    """写配置（upsert）；同时写描述"""
    from app.models.sys_config import SysConfig
    str_val = str(value)
    row = db.query(SysConfig).filter(SysConfig.key == key).first()
    if row:
        row.value = str_val
        if description is not None:
            row.description = description
    else:
        db.add(SysConfig(key=key, value=str_val, description=description))
    db.commit()
    with _lock:
        _cache.pop(key, None)


def invalidate(key: Optional[str] = None) -> None:
    with _lock:
        if key:
            _cache.pop(key, None)
        else:
            _cache.clear()
