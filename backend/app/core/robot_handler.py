"""
钉钉企业内部机器人（单聊）处理器
=================================
维修员在钉钉中单聊机器人，通过自然语言完成：
- 帮助菜单
- 工单状态查询（输入工单号）
- 我的待办工单列表
- 设备故障知识检索（向量检索知识库）

身份识别：
- 优先按 unionId 匹配（扫码绑定时已持久化 dingtalk_union_id）
- 其次按 senderStaffId（企业 userId）匹配 dingtalk_userid

回复方式：机器人单聊消息 API /v1.0/robot/oToMessages/batchSend
"""
from __future__ import annotations

import json
import re
import time
import requests
from typing import Optional, Dict, List

from loguru import logger

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.user import User
from app.agents.robot_graph import invoke_robot, HELP_TEXT

# 机器人编码：默认 = 应用 AppKey（用户确认 RobotCode=dingqqvdduyaaefhwg6z），可被 .env 覆盖
ROBOT_CODE = getattr(settings, "DINGTALK_ROBOT_CODE", "") or settings.DINGTALK_APP_KEY
ROBOT_REPLY_API = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"


# ============================================================
# 回复消息
# ============================================================
def _send_reply(user_ids: List[str], content: str, title: str = "", msg_key: str = "sampleMarkdown") -> bool:
    """通过机器人单聊 API 回复用户"""
    if not user_ids:
        return False
    try:
        from app.core.dingtalk import dingtalk
        token = dingtalk._get_access_token()
    except Exception as e:
        logger.error(f"[Robot] 获取 token 失败，无法回复: {e}")
        return False

    try:
        if msg_key == "sampleMarkdown":
            msg_param = json.dumps({"title": title or "维修助手", "text": content}, ensure_ascii=False)
        else:
            msg_param = json.dumps({"content": content}, ensure_ascii=False)
        resp = requests.post(
            ROBOT_REPLY_API,
            headers={"x-acs-dingtalk-access-token": token},
            json={
                "robotCode": ROBOT_CODE,
                "userIds": user_ids,
                "msgKey": msg_key,
                "msgParam": msg_param,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("processQueryKey") or data.get("errcode") in (0, None):
            logger.info(f"[Robot] 回复成功: users={len(user_ids)}")
            return True
        logger.error(f"[Robot] 回复失败: {data}")
        return False
    except Exception as e:
        logger.exception(f"[Robot] 回复异常: {e}")
        return False


# ============================================================
# 身份识别
# ============================================================
def _find_user(db, payload: Dict) -> Optional[User]:
    union_id = (payload.get("unionId") or "").strip()
    staff_id = (payload.get("senderStaffId") or "").strip()
    if union_id:
        u = db.query(User).filter(User.dingtalk_union_id == union_id).first()
        if u:
            return u
    if staff_id:
        u = db.query(User).filter(User.dingtalk_userid == staff_id).first()
        if u:
            return u
    return None


def _auto_bind(db, sender_staff_id: str) -> Optional[User]:
    """收到机器人消息但未匹配到系统用户时，用企业 userId 查钉钉通讯录，
    按 unionId / 手机号 / 姓名自动回填绑定，实现免手动重新绑定的自动识别。"""
    if not sender_staff_id:
        return None
    try:
        from app.core.dingtalk import dingtalk
        detail = dingtalk.get_user_detail(sender_staff_id)
        if not detail or detail.get("_mock"):
            logger.warning(f"[Robot] 通讯录查询失败，无法自动绑定: staffId={sender_staff_id}")
            return None
        union_id = (detail.get("union_id") or "").strip()
        mobile = (detail.get("mobile") or "").strip()
        name = (detail.get("name") or "").strip()
        user = None
        if union_id:
            user = db.query(User).filter(User.dingtalk_union_id == union_id).first()
        if not user and mobile:
            user = db.query(User).filter(User.phone == mobile).first()
        if not user and name:
            user = db.query(User).filter(User.real_name == name).first()
        if user:
            user.dingtalk_userid = sender_staff_id
            if union_id:
                user.dingtalk_union_id = union_id
            if name:
                user.dingtalk_name = name
            db.commit()
            logger.info(f"[Robot] 自动绑定成功: staffId={sender_staff_id} -> user={user.real_name}")
        else:
            logger.warning(f"[Robot] 通讯录查到但系统无匹配用户: staffId={sender_staff_id} name={name} mobile={mobile}")
        return user
    except Exception as e:
        logger.warning(f"[Robot] 自动绑定异常: {e}")
        return None


# ============================================================
# 意图路由（LangGraph 图与子图实现，见 app/agents/robot_graph.py）
# ============================================================
def _is_knowledge_query(text: str) -> bool:
    """判断消息是否为知识检索类（非帮助/待办/工单号/库存/录入）"""
    text = (text or "").strip()
    if not text:
        return False
    if any(k in text for k in ("帮助", "菜单", "功能", "help", "hello", "你好")):
        return False
    if any(k in text for k in ("我的待办", "我的工单", "待办", "代办", "任务")):
        return False
    if any(k in text for k in ("录入工单", "新增工单", "创建工单", "工单录入", "报修")):
        return False
    if any(k in text for k in ("库存", "备件", "零件", "配件", "备品", "还有多少", "还剩多少", "查库存", "剩下", "够不够", "缺不缺")):
        return False
    if any(k in text for k in ("排班", "值班", "班表", "班次")):
        return False
    if re.search(r"WO[-_ ]?[\d-]{6,}", text, re.IGNORECASE) or re.search(r"\d{6,}", text):
        return False
    return True


def _route(db, payload: Dict, user: Optional[User], text: str) -> str:
    """意图路由：委托 LangGraph 图与子图完成"""
    staff_id = (payload.get("senderStaffId") or "").strip()
    return invoke_robot(
        text=text,
        staff_id=staff_id,
        user_id=user.id if user else None,
        user_dt_userid=(user.dingtalk_userid or "") if user else "",
    )


# ============================================================
# 入口
# ============================================================
def handle_robot_message(payload: Dict) -> None:
    """Stream 收到机器人单聊消息时调用（同步处理）"""
    try:
        text = ""
        if isinstance(payload.get("text"), dict):
            text = payload["text"].get("content", "")
        elif payload.get("text"):
            text = str(payload["text"])
        sender_staff_id = (payload.get("senderStaffId") or "").strip()
        sender_nick = (payload.get("senderNick") or "").strip()
        msg_type = payload.get("msgtype") or payload.get("msgType") or ""

        # 只处理文本消息
        if msg_type and msg_type != "text":
            logger.info(f"[Robot] 忽略非文本消息: msgtype={msg_type}")
            return

        logger.info(f"[Robot] 收到消息: sender={sender_nick}({sender_staff_id}) content={text[:80]}")

        db = SessionLocal()
        try:
            user = _find_user(db, payload)
            if not user and sender_staff_id:
                # 自动绑定：用企业 userId 查通讯录匹配系统用户
                user = _auto_bind(db, sender_staff_id)
                if not user:
                    user = _find_user(db, payload)
            if not user:
                logger.warning(f"[Robot] 未匹配到系统用户: staffId={sender_staff_id}, unionId={payload.get('unionId')}")
                _send_reply([sender_staff_id] if sender_staff_id else [], HELP_TEXT)
                return
            # 知识检索类消息：LLM 生成较慢，先发"正在思考中"占位提示
            if _is_knowledge_query(text) and sender_staff_id:
                _send_reply([sender_staff_id], "思考中，请稍候…", title="维修助手")
            reply = _route(db, payload, user, text)
            _send_reply([sender_staff_id] if sender_staff_id else [], reply, title="维修助手")
        finally:
            db.close()
    except Exception as e:
        logger.exception(f"[Robot] 处理消息异常: {e}")
