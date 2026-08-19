from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from passlib.context import CryptContext
from loguru import logger
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.cache_service import cache_service
from app.models.user import User, UserRole
from app.schemas import UserCreate, UserUpdate, UserResponse, PaginatedResponse

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _u_to_dict(u: User) -> dict:
    return {c.name: getattr(u, c.name) for c in u.__table__.columns if c.name != 'password_hash'}


@router.get("/me", summary="获取当前登录用户信息")
def get_current_user_me(current_user: User = Depends(get_current_user)):
    """返回当前登录用户的完整信息（含钉钉绑定状态）"""
    return _u_to_dict(current_user)


@router.get("/", response_model=PaginatedResponse[UserResponse], summary="获取用户列表")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=1000),
    role: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if keyword:
        query = query.filter(
            User.username.ilike(f"%{keyword}%") |
            User.real_name.ilike(f"%{keyword}%")
        )
    total = query.count()
    items = query.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_u_to_dict(u) for u in items], "page": page, "page_size": page_size}


@router.get("/{user_id}", response_model=UserResponse, summary="获取用户详情（带缓存）")
def get_user(user_id: int, db: Session = Depends(get_db)):
    cache_key = f"user:{user_id}"
    cached = cache_service.get(cache_key)
    if cached:
        return cached

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    result = _u_to_dict(user)
    cache_service.set(cache_key, result, ttl=300)
    return result


@router.post("/", response_model=UserResponse, summary="创建用户")
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    data_dict = data.model_dump()
    data_dict["password_hash"] = pwd_context.hash(data_dict.pop("password"))
    user = User(**data_dict)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserResponse, summary="更新用户")
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(user, key, val)
    db.commit()
    db.refresh(user)
    cache_service.delete(f"user:{user_id}")
    return user


@router.delete("/{user_id}", summary="删除用户")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.delete(user)
    db.commit()
    cache_service.delete(f"user:{user_id}")
    return {"message": "用户已删除"}


@router.post("/{user_id}/dingtalk/unbind", summary="管理员代解绑钉钉")
def admin_unbind_dingtalk(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """管理员代员工解绑钉钉账号（应对员工离职场景）"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="仅管理员可代解绑")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not user.dingtalk_userid:
        raise HTTPException(status_code=400, detail="该用户未绑定钉钉")

    user.dingtalk_userid = None
    user.dingtalk_bound_at = None
    db.commit()
    cache_service.delete(f"user:{user_id}")
    logger.info(f"[User] 管理员代解绑钉钉: target_user={user_id}, admin={current_user.id}")
    return {"message": f"已解绑用户「{user.real_name}」的钉钉账号"}