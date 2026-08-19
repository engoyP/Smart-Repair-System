from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.category import Category
from app.models.user import User
from app.schemas import CategoryCreate, CategoryUpdate, CategoryResponse

router = APIRouter()


def build_category_tree(categories: List[Category], parent_id: Optional[int] = None) -> List[dict]:
    """递归构建分类树"""
    result = []
    for cat in categories:
        if cat.parent_id == parent_id:
            node = {
                "id": cat.id,
                "name": cat.name,
                "code": cat.code,
                "parent_id": cat.parent_id,
                "category_type": cat.category_type,
                "sort_order": cat.sort_order,
                "description": cat.description,
                "created_at": cat.created_at,
                "updated_at": cat.updated_at,
                "children": build_category_tree(categories, cat.id)
            }
            result.append(node)
    return result


@router.get("/", summary="获取分类列表（树形结构）")
def list_categories(
    category_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Category)
    if category_type:
        query = query.filter(Category.category_type == category_type)
    all_categories = query.order_by(Category.sort_order, Category.id).all()
    tree = build_category_tree(all_categories)
    return {"items": tree, "total": len(all_categories)}


@router.get("/{category_id}", response_model=CategoryResponse, summary="获取分类详情")
def get_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    return cat


@router.post("/", response_model=CategoryResponse, summary="创建分类")
def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    existing = db.query(Category).filter(Category.code == data.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="分类编码已存在")
    cat = Category(**data.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.put("/{category_id}", response_model=CategoryResponse, summary="更新分类")
def update_category(category_id: int, data: CategoryUpdate, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(cat, key, val)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{category_id}", summary="删除分类")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    # 将子分类的 parent_id 置空
    db.query(Category).filter(Category.parent_id == category_id).update({"parent_id": None})
    db.delete(cat)
    db.commit()
    return {"message": "分类已删除"}