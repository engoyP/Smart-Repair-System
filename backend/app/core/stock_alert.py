"""库存预警定时检查

定期扫描备件库存，低于安全线时发送钉钉预警通知。
可通过 /api/v1/spare-parts/check-alerts 手动触发。
"""
from typing import List, Dict
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.notification import notification_service
from app.models.spare_part import SparePart


def check_and_notify_stock_alerts(db: Session = None) -> Dict:
    """
    检查库存并发送预警通知
    返回预警结果摘要
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        low_stock = db.query(SparePart).filter(
            SparePart.stock_quantity > 0,
            SparePart.stock_quantity <= SparePart.safety_stock,
        ).all()

        out_of_stock = db.query(SparePart).filter(
            SparePart.stock_quantity <= 0,
        ).all()

        alerts: List[Dict] = []

        for p in low_stock:
            alerts.append({
                "part_name": p.part_name,
                "part_code": p.part_code,
                "stock": p.stock_quantity,
                "safety": p.safety_stock,
                "device_type": p.device_type,
                "level": "low_stock",
            })

        for p in out_of_stock:
            alerts.append({
                "part_name": p.part_name,
                "part_code": p.part_code,
                "stock": p.stock_quantity,
                "safety": p.safety_stock,
                "device_type": p.device_type,
                "level": "out_of_stock",
            })

        if alerts:
            logger.warning(f"[StockAlert] 发现 {len(alerts)} 项库存预警")
            try:
                notification_service.notify_inventory_alert(
                    userid="admin",
                    items=alerts,
                    db=db,
                )
            except Exception as e:
                logger.warning(f"[StockAlert] 预警通知发送失败: {e}")
        else:
            logger.info("[StockAlert] 库存检查完成，无预警")

        return {
            "low_stock_count": len(low_stock),
            "out_of_stock_count": len(out_of_stock),
            "alert_count": len(alerts),
            "alerts": alerts[:20],
        }

    finally:
        if close_db:
            db.close()


def run_periodic_check(interval_seconds: int = 3600):
    """
    后台定时检查（可通过 FastAPI BackgroundTasks 或 APScheduler 调用）
    默认每 3600 秒（1 小时）检查一次
    """
    import time
    logger.info(f"[StockAlert] 启动定时检查，间隔 {interval_seconds}s")
    while True:
        try:
            result = check_and_notify_stock_alerts()
            if result["alert_count"] > 0:
                logger.warning(f"[StockAlert] 预警: {result['alert_count']} 项")
        except Exception as e:
            logger.error(f"[StockAlert] 定时检查异常: {e}")
        time.sleep(interval_seconds)