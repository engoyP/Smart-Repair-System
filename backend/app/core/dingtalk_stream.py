"""
钉钉 Stream 模式客户端（基于官方 dingtalk-stream SDK）
======================================================

重要提醒（Stream 模式必须看）：
  钉钉 Stream 的握手/鉴权协议没有公开手写版本，必须使用官方 Python SDK。
  所以本模块**只支持官方 dingtalk-stream SDK**，请先安装：
      pip install dingtalk-stream

  如果没装 → Stream 客户端会跳过启动（不影响主服务），你仍然可以用两种方式兜底：
  (a) 每天 01:00 APScheduler 自动扫近 3 天审批单同步
  (b) 主管手动调   POST /dingtalk/schedule/sync-oa-leaves?days=1

为什么不手写 WebSocket？
  Stream 模式的连接地址、鉴权签名算法、事件 topic 订阅协议都由 SDK 内部维护，
  且每个大版本会变，手写实现无法长期维护。官方 SDK 还自带断线重连/心跳/ACK，生产级稳定。

工作原理（SDK 内部做的）：
  1. SDK 用 app_key/app_secret 向 Stream 网关换取临时 ticket
  2. 建立长连接 WebSocket，内部 ping/pong 保活
  3. 订阅事件 topic → 收到 bpms_instance_change 后回调我们的 handler
  4. ACK 回执 → 钉钉确认不重复推送
"""
from __future__ import annotations

import asyncio
import threading
from typing import Optional, Dict, Any, Callable

from loguru import logger

from app.core.config import settings
from app.core import dingtalk_oa_config as OA_CFG
from app.core import dingtalk_oa_sync

try:
    from dingtalk_stream import (
        CallbackHandler,
        CallbackMessage,
        AckMessage,
    )
except ImportError:  # SDK 未安装时兜底（实际 _sdk_forever_sync 内会再次检查）
    CallbackHandler = object
    CallbackMessage = object
    AckMessage = object


# ============================================================
# 默认事件处理器：收到 OA 审批事件就走 oa_sync，其他事件打日志
# ============================================================
def default_event_handler(event: Dict[str, Any]) -> Optional[Any]:
    """默认事件处理函数：目前只关心 bpms_instance_change

    新版 Stream SDK 推送的事件没有 EventType 字段，事件类型在 resource 字段里：
      resource = "/v1.0/event/bpms_instance_change/processCode/PROC-xxx/type/finish"
    旧版 HTTP 回调才有 EventType = "bpms_instance_change"
    """
    try:
        # 1. 旧版：直接看 EventType / eventType 字段
        t = (event.get("EventType") or event.get("eventType") or "")
        # 2. 新版 Stream：从 resource 字段提取事件类型
        resource = event.get("resource") or ""
        if not t and resource and "bpms_" in resource:
            # resource 格式: /v1.0/event/bpms_instance_change/processCode/xxx/type/finish
            parts = resource.strip("/").split("/")
            t = parts[2] if len(parts) > 2 else ""  # bpms_instance_change
        # 3. type 字段（start/finish）单独看，不能当事件类型
        if "bpms" in t.lower() or "bpms" in resource.lower():
            return dingtalk_oa_sync.handle_oa_event(event)
        logger.info(f"[DingStream] 收到非OA审批事件（忽略）type={t} resource={resource[:80]}")
        return None
    except Exception as e:
        logger.exception(f"[DingStream] 处理事件异常: {e}")
        return None


class RobotMessageCallbackHandler(CallbackHandler):
    """企业内部机器人单聊消息回调：topic 固定值 /v1.0/im/bot/messages/get

    注意：机器人单聊消息是 CALLBACK 类型（不是 EVENT），必须用
    register_callback_handler 显式订阅，register_all_event_handler 收不到。
    """

    async def process(self, message: CallbackMessage):
        try:
            payload = message.data or {}
            logger.info(f"[DingStream-SDK] 收到机器人消息 payload={str(payload)[:500]}")
            from app.core import robot_handler
            robot_handler.handle_robot_message(payload)
        except Exception as e:
            logger.exception(f"[DingStream-SDK] 机器人消息处理失败: {e}")
        return AckMessage.STATUS_OK, "OK"


class CardButtonCallbackHandler(CallbackHandler):
    """互动卡片按钮回调：topic 固定值 CallbackHandler.TOPIC_CARD_CALLBACK

    派工进度确认卡片（确认接受/已到达/开始维修等）的按钮点击后走这里。
    """

    async def process(self, message: CallbackMessage):
        try:
            payload = message.data or {}
            logger.info(f"[DingStream-SDK] 收到卡片回调 payload={str(payload)[:500]}")
            from app.core import dingtalk_wo_card
            reply_text = dingtalk_wo_card.handle_card_callback(payload)
            # 把操作结果回复给用户（走机器人单聊消息，与卡片同一会话）
            if reply_text:
                user_id = (payload.get("userId") or "").strip()
                if user_id:
                    from app.core.robot_handler import _send_reply
                    _send_reply([user_id], reply_text, title="维修助手")
        except Exception as e:
            logger.exception(f"[DingStream-SDK] 卡片回调处理失败: {e}")
        return AckMessage.STATUS_OK, "OK"


# ============================================================
# 后台常驻线程：跑 asyncio 事件循环，启动官方 Stream SDK
# ============================================================
class DingTalkStreamRunner:
    """后台线程里启动官方 Stream SDK 客户端，FastAPI 关闭时自动停掉"""

    _instance = None

    def __init__(self, handler: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self.handler = handler or default_event_handler
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client_task: Optional[asyncio.Task] = None
        self._client_ref = None  # 官方 StreamClient 引用（shutdown 用）

    # ------------------------------------------------------------
    # 启动/停止（FastAPI startup / shutdown 调用）
    # ------------------------------------------------------------
    def start(self):
        if not OA_CFG.STREAM_MODE:
            logger.info("[DingStream] ⚙️ DINGTALK_STREAM_MODE=false → 跳过Stream客户端启动（如需启用请改.env=true）")
            return
        if settings.DINGTALK_MOCK_MODE:
            logger.info("[DingStream] 🧪 DINGTALK_MOCK_MODE=true → 跳过Stream客户端启动（用mock）")
            return
        if not (settings.DINGTALK_APP_KEY and settings.DINGTALK_APP_SECRET):
            logger.warning(
                "[DingStream] ⚠️ 未配置 DINGTALK_APP_KEY/APP_SECRET，跳过Stream客户端启动。"
                "请在 .env 填写凭证，或改用 HTTP 回调模式"
            )
            return
        if self._thread and self._thread.is_alive():
            logger.warning("[DingStream] 已有 Stream 客户端在运行，不重复启动")
            return

        # 提前检查 dingtalk-stream SDK 是否安装
        try:
            import dingtalk_stream  # noqa: F401
        except ImportError:
            logger.error(
                "\n"
                "══════════════════════════════════════════════════════════════\n"
                "  ⚠️  未检测到官方 dingtalk-stream SDK！\n"
                "  Stream 模式必须安装（钉钉后台会报 Stream模式接入失败）\n"
                "  请执行：\n"
                "        pip install dingtalk-stream\n"
                "  然后重启后端即可。\n"
                "  当前服务仍然可用：每天01:00自动扫 + 手动 sync-oa-leaves 兜底。\n"
                "══════════════════════════════════════════════════════════════"
            )
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_event_loop, name="DingStream", daemon=True)
        self._thread.start()
        logger.info("[DingStream] ✅ Stream 客户端后台线程已启动（基于官方 dingtalk-stream SDK）")

    def stop(self):
        self._stop_event.set()
        try:
            if self._loop and self._client_task:
                fut = asyncio.run_coroutine_threadsafe(self._shutdown_task(), self._loop)
                fut.result(timeout=5)
        except Exception as e:
            logger.warning(f"[DingStream] stop 异常（忽略即可）: {e}")

    async def _shutdown_task(self):
        if self._client_ref is not None:
            try:
                await self._client_ref.shutdown()
            except Exception:
                pass
        if self._client_task and not self._client_task.done():
            self._client_task.cancel()
            try:
                await self._client_task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------
    # 内部：后台线程直接同步调用官方 SDK（SDK 内部自带 asyncio 事件循环）
    # ------------------------------------------------------------
    def _run_event_loop(self):
        """后台线程入口：直接同步调用 SDK 的 start_forever()

        注意：dingtalk-stream SDK 的 start_forever() 是同步方法，
        内部会自己创建 asyncio 事件循环。不能在外层再包 asyncio.run()，
        否则报 "asyncio.run() cannot be called from a running event loop"
        """
        try:
            self._sdk_forever_sync()
        except Exception as e:
            logger.exception(f"[DingStream] 事件循环异常退出（将由重启机制恢复）: {e}")

    def _sdk_forever_sync(self):
        """同步版：直接调 client.start_forever()，SDK 内部自建事件循环"""
        try:
            from dingtalk_stream import (
                DingTalkStreamClient,
                EventHandler,
                EventMessage,
                Credential,
                AckMessage,
            )
        except ImportError as e:
            logger.error(f"[DingStream] 缺少官方 dingtalk-stream SDK: {e}. 请先 pip install dingtalk-stream")
            import time
            time.sleep(60)
            return

        runner_ref = self

        class _OurEventHandler(EventHandler):
            """继承 SDK 的 EventHandler，在 process() 里把 EventMessage 转 dict 交给业务 handler"""

            async def process(self, event: EventMessage):
                payload = {}
                try:
                    if hasattr(event, "data") and isinstance(event.data, dict):
                        payload = event.data
                    headers_info = {}
                    if hasattr(event, "headers"):
                        for k in ("message_id", "topic", "eventId", "event_type"):
                            v = getattr(event.headers, k, None)
                            if v:
                                headers_info[f"_headers.{k}"] = v
                    for key in ("body", "event", "data", "message"):
                        if isinstance(payload.get(key), dict) and not any(
                            x in payload
                            for x in ("EventType", "eventType", "processInstanceId", "type", "bpmsInstanceId")
                        ):
                            inner = payload[key]
                            if isinstance(inner, dict) and any(
                                x in inner
                                for x in ("EventType", "eventType", "processInstanceId", "type", "bpmsInstanceId")
                            ):
                                payload = inner
                                break
                    payload.update(headers_info)
                    summary = str(payload)[:500]
                    logger.info(f"[DingStream-SDK] 收到事件 payload={summary}")
                except Exception as e:
                    logger.exception(f"[DingStream-SDK] 解析 EventMessage 异常: {e}")

                try:
                    runner_ref.handler(payload or {})
                except Exception as e:
                    logger.exception(f"[DingStream-SDK] 业务 handler 处理失败: {e}")
                return AckMessage.STATUS_OK, "OK"

        cred = Credential(
            client_id=settings.DINGTALK_APP_KEY,
            client_secret=settings.DINGTALK_APP_SECRET,
        )
        client = DingTalkStreamClient(credential=cred)
        client.register_all_event_handler(_OurEventHandler())
        # 机器人单聊消息：CALLBACK 类型，必须显式订阅 topic /v1.0/im/bot/messages/get
        client.register_callback_handler("/v1.0/im/bot/messages/get", RobotMessageCallbackHandler())
        # 互动卡片按钮回调（派工进度确认）
        client.register_callback_handler(CallbackHandler.TOPIC_CARD_CALLBACK, CardButtonCallbackHandler())
        self._client_ref = client

        logger.info(
            "[DingStream-SDK] 🔗 正在连接钉钉 Stream 网关..."
            " 连接成功后钉钉后台红色「Stream模式接入失败」会自动消失。"
        )

        reconnect_gap = OA_CFG.STREAM_RECONNECT_INTERVAL
        import time
        while not self._stop_event.is_set():
            try:
                # SDK 的 start_forever() 是同步阻塞方法，内部自带 asyncio 事件循环
                client.start_forever()
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.warning(
                    f"[DingStream-SDK] Stream 连接异常（{reconnect_gap}s 后自动重连）: {e}"
                )
                # 重建 client 避免内部状态脏
                client = DingTalkStreamClient(credential=cred)
                client.register_all_event_handler(_OurEventHandler())
                client.register_callback_handler("/v1.0/im/bot/messages/get", RobotMessageCallbackHandler())
                client.register_callback_handler(CallbackHandler.TOPIC_CARD_CALLBACK, CardButtonCallbackHandler())
                self._client_ref = client
                time.sleep(reconnect_gap)


# ============================================================
# 导出一个单例，FastAPI 启动时直接 start/stop 就行
# ============================================================
_stream_runner = DingTalkStreamRunner()


def start_stream_in_background():
    """FastAPI startup 时调用"""
    _stream_runner.start()


def stop_stream_background():
    """FastAPI shutdown 时调用"""
    _stream_runner.stop()
