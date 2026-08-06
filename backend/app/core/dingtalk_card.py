"""钉钉互动卡片封装（MarkdownButton 模板）

能力：
- send_card(): 创建并投放单聊互动卡片到机器人会话，返回 (out_track_id, err_msg)
- update_card(): 更新已投递卡片（刷新按钮/内容）
- request_button(): 生成回传按钮（params.id 为自定义动作标识）

说明：
- 使用官方公共 MarkdownButton 卡片模板（支持 title / markdown / msgButtons），
  按钮 request=true 时点击会触发卡片回调（Stream 订阅 CallbackHandler.TOPIC_CARD_CALLBACK）。
- 该模板为普通卡片，无 AI 生命周期，渲染稳定（AI Markdown 模板会一直停在"处理中"）。
- 需要应用开通「Card.Instance.Write 互动卡片实例写」权限，否则 403。
"""
from __future__ import annotations

import json
import uuid
from typing import Dict, List, Optional, Tuple

import requests
from loguru import logger

# 官方公共 MarkdownButton 卡片模板（已验证可正常渲染+按钮回调）
CARD_TEMPLATE_ID = "1366a1eb-bc54-4859-ac88-517c56a9acb1.schema"

CARD_API = "https://api.dingtalk.com/v1.0/card/instances"


def _get_token() -> str:
    from app.core.dingtalk import dingtalk
    return dingtalk._get_access_token()


def _headers() -> dict:
    return {"x-acs-dingtalk-access-token": _get_token()}


def _friendly_error(err: str) -> str:
    """把常见 API 错误转成可读中文提示"""
    err = err or ""
    if "Forbidden.AccessDenied.AccessTokenPermissionDenied" in err or "权限" in err:
        from app.core.config import settings
        appkey = settings.DINGTALK_APP_KEY
        apply_url = f"https://open-dev.dingtalk.com/appscope/apply?content={appkey}%23Card.Instance.Write"
        return (
            "缺少互动卡片权限（Card.Instance.Write），请到钉钉开放平台开通后重试：\n"
            f"{apply_url}"
        )
    if "timeout" in err.lower() or "Timed out" in err:
        return "钉钉接口超时，请稍后重试"
    return err


def request_button(text: str, action: str, color: str = "blue") -> dict:
    """生成回传按钮。点击后回调 payload 的 cardPrivateData.params.id = action"""
    return {
        "text": text,
        "color": color,
        "request": True,
        "params": {"id": action},
    }


def _build_card_data(title: str, markdown: str, buttons: List[dict]) -> dict:
    """构造 MarkdownButton 模板的 cardData（模板变量必须放在 cardParamMap 中）。

    sys_full_json_obj 为 JSON 字符串，承载按钮列表。
    """
    return {
        "cardParamMap": {
            "title": title or "",
            "markdown": markdown or "",
            "tips": "",
            "sys_full_json_obj": json.dumps({"msgButtons": buttons or []}, ensure_ascii=False),
        }
    }


def send_card(
    userid: str,
    title: str,
    markdown: str,
    buttons: List[dict],
    out_track_id: Optional[str] = None,
) -> Tuple[str, str]:
    """创建并投放互动卡片到用户与机器人的单聊会话。

    使用「创建并投放卡片」接口（createAndDeliver），openSpaceId 指向 IM_ROBOT 单聊场域。
    该方式已在生产验证可正常渲染与按钮回调。

    Returns:
        (out_track_id, err_msg)：err_msg 非空表示发送失败。
    """
    oid = out_track_id or f"card_{uuid.uuid4().hex[:16]}"
    body = {
        "cardTemplateId": CARD_TEMPLATE_ID,
        "outTrackId": oid,
        "callbackType": "STREAM",  # 按钮回调走 Stream 模式（TOPIC_CARD_CALLBACK）
        "cardData": _build_card_data(title, markdown, buttons),
        "openSpaceId": f"dtv1.card//IM_ROBOT.{userid}",
        "imRobotOpenSpaceModel": {"supportForward": False},
        "imRobotOpenDeliverModel": {"spaceType": "IM_ROBOT"},
        "userIdType": 1,
    }
    try:
        resp = requests.post(
            "https://api.dingtalk.com/v1.0/card/instances/createAndDeliver",
            headers=_headers(),
            json=body,
            timeout=10,
        )
        data = resp.json()
        deliver_ok = False
        for dr in ((data.get("result") or {}).get("deliverResults") or []):
            if dr.get("spaceType") == "IM_ROBOT" and dr.get("success"):
                deliver_ok = True
                break
        if data.get("success") and deliver_ok:
            logger.info(f"[DingCard] 卡片已投递: staff={userid} outTrackId={oid}")
            return oid, ""
        err = data.get("message") or data.get("errmsg") or data.get("code") or str(data)
        logger.error(f"[DingCard] 创建并投放卡片失败: {data}")
        return oid, _friendly_error(str(err))
    except Exception as e:
        logger.exception(f"[DingCard] 发送卡片异常: {e}")
        return oid, _friendly_error(str(e))


def update_card(out_track_id: str, title: str, markdown: str, buttons: List[dict]) -> bool:
    """更新已投递卡片（刷新内容与按钮）"""
    if not out_track_id:
        return False
    body = {
        "outTrackId": out_track_id,
        "cardData": _build_card_data(title, markdown, buttons),
    }
    try:
        resp = requests.put(CARD_API, headers=_headers(), json=body, timeout=10)
        data = resp.json()
        ok = data.get("success") or data.get("processQueryKey")
        if ok:
            logger.info(f"[DingCard] 卡片已更新: {out_track_id}")
        else:
            logger.warning(f"[DingCard] 更新卡片失败 {out_track_id}: {data}")
        return bool(ok)
    except Exception as e:
        logger.warning(f"[DingCard] 更新卡片异常 {out_track_id}: {e}")
        return False
