"""NotificationService - 统一通知服务

抽象消息推送接口，支持：
- 派工通知
- 维修完成通知
- 库存预警通知
- 工单审核通知
- 管理员通知
"""
from typing import Optional, List, Dict
from loguru import logger
from sqlalchemy.orm import Session

from app.core.dingtalk import dingtalk
from app.core.config import settings


class NotificationService:
    """通知服务"""

    def __init__(self):
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled and not settings.DINGTALK_MOCK_MODE

    def notify_dispatch(self, userid: str, work_order_no: str, device: str,
                       db: Optional[Session] = None) -> bool:
        """派工通知"""
        logger.info(f"[Notification] 派工通知: {work_order_no} → {userid}")
        return dingtalk.send_dispatch_notice(userid, work_order_no, device)

    def notify_completion(self, userid: str, work_order_no: str, device: str,
                          summary: str = "", db: Optional[Session] = None) -> bool:
        """维修完成通知"""
        logger.info(f"[Notification] 完成通知: {work_order_no} → {userid}")
        return dingtalk.send_completion_notice(userid, work_order_no, device, summary)

    def notify_inventory_alert(self, userid: str, items: List[Dict],
                                db: Optional[Session] = None) -> bool:
        """库存预警通知"""
        logger.info(f"[Notification] 库存预警 → {userid}, {len(items)} 项")
        return dingtalk.send_inventory_alert(userid, items)

    def notify_approval_request(self, userid: str, work_order_no: str, device: str,
                                confidence: float, description: str,
                                review_url: str = "", db: Optional[Session] = None) -> bool:
        """工单审核通知"""
        logger.info(f"[Notification] 审核通知: {work_order_no} (置信度={confidence:.2f}) → {userid}")
        return dingtalk.send_approval_request(
            userid, work_order_no, device, confidence, description, review_url
        )

    def notify_admin_approval(self, work_order_no: str, device: str,
                               confidence: float, description: str,
                               review_url: str = "") -> bool:
        """向所有管理员推送审核通知"""
        logger.info(f"[Notification] 管理员审核通知: {work_order_no}")
        content = f"""## 待审核工单
- **工单编号**: {work_order_no}
- **设备**: {device}
- **置信度**: {confidence:.0%}
- **描述**: {description[:100]}

请及时登录管理后台处理。
"""
        return dingtalk.send_work_notice_to_admin(
            f"待审核: {work_order_no}", content, url=review_url
        )

    def notify_batch(self, userids: List[str], title: str, content: str, url: str = "") -> Dict:
        """批量通知"""
        results = {}
        for uid in userids:
            results[uid] = dingtalk.send_work_notice(uid, title, content, url)
        return results


notification_service = NotificationService()