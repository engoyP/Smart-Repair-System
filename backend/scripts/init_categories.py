"""初始化分类数据 - 设备类型、故障类型等"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.category import Category

db = SessionLocal()

# 设备类型数据（精密五金工厂场景）
DEVICE_TYPES = [
    {"name": "CNC车床", "code": "CNC-L", "sort_order": 1},
    {"name": "CNC加工中心", "code": "CNC-M", "sort_order": 2},
    {"name": "冲床", "code": "STP", "sort_order": 3},
    {"name": "激光切割机", "code": "LASER", "sort_order": 4},
    {"name": "数控折弯机", "code": "BEND", "sort_order": 5},
    {"name": "线切割", "code": "WEDM", "sort_order": 6},
    {"name": "磨床", "code": "GRIND", "sort_order": 7},
    {"name": "空压机", "code": "AC", "sort_order": 8},
]

# 故障类型数据
FAULT_TYPES = [
    {"name": "机械故障", "code": "MECH", "sort_order": 1},
    {"name": "电气故障", "code": "ELEC", "sort_order": 2},
    {"name": "液压故障", "code": "HYDRAULIC", "sort_order": 3},
    {"name": "气动故障", "code": "PNEUMATIC", "sort_order": 4},
    {"name": "控制故障", "code": "CONTROL", "sort_order": 5},
    {"name": "传感故障", "code": "SENSOR", "sort_order": 6},
]

# 知识库类型数据
KNOWLEDGE_TYPES = [
    {"name": "故障诊断", "code": "DIAGNOSIS", "sort_order": 1},
    {"name": "维修方案", "code": "SOLUTION", "sort_order": 2},
    {"name": "预防维护", "code": "PREVENTIVE", "sort_order": 3},
]

def init_categories():
    """初始化分类数据"""
    created_count = 0
    
    # 1. 设备类型
    for item in DEVICE_TYPES:
        existing = db.query(Category).filter(
            Category.code == item["code"],
            Category.category_type == "DEVICE_TYPE"
        ).first()
        if not existing:
            cat = Category(
                name=item["name"],
                code=item["code"],
                category_type="DEVICE_TYPE",
                sort_order=item["sort_order"],
                description=f"设备类型: {item['name']}"
            )
            db.add(cat)
            created_count += 1
            print(f"[新增] 设备类型: {item['name']} ({item['code']})")
        else:
            print(f"[已存在] 设备类型: {item['name']} ({item['code']})")
    
    # 2. 故障类型
    for item in FAULT_TYPES:
        existing = db.query(Category).filter(
            Category.code == item["code"],
            Category.category_type == "FAULT_TYPE"
        ).first()
        if not existing:
            cat = Category(
                name=item["name"],
                code=item["code"],
                category_type="FAULT_TYPE",
                sort_order=item["sort_order"],
                description=f"故障类型: {item['name']}"
            )
            db.add(cat)
            created_count += 1
            print(f"[新增] 故障类型: {item['name']} ({item['code']})")
        else:
            print(f"[已存在] 故障类型: {item['name']} ({item['code']})")
    
    # 3. 知识库类型
    for item in KNOWLEDGE_TYPES:
        existing = db.query(Category).filter(
            Category.code == item["code"],
            Category.category_type == "KNOWLEDGE_TYPE"
        ).first()
        if not existing:
            cat = Category(
                name=item["name"],
                code=item["code"],
                category_type="KNOWLEDGE_TYPE",
                sort_order=item["sort_order"],
                description=f"知识库类型: {item['name']}"
            )
            db.add(cat)
            created_count += 1
            print(f"[新增] 知识库类型: {item['name']} ({item['code']})")
        else:
            print(f"[已存在] 知识库类型: {item['name']} ({item['code']})")
    
    db.commit()
    print(f"\n完成! 共新增 {created_count} 条分类数据")

if __name__ == "__main__":
    init_categories()
    db.close()
