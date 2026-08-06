"""
钉钉 OA 审批同步配置
====================

所有配置都从环境变量（.env）读取，模板未建好 / 字段名没对上时也能运行（只是不做落库操作，打日志提醒）。
未来你在钉钉后台建好请假审批模板，改完 .env 重启后端即可生效，不需要改代码。
"""
from __future__ import annotations

import os
from typing import Dict

# 确保 .env 在模块级 os.getenv 之前加载（防止 import 顺序问题）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# 1. 推送模式切换：Stream (WebSocket 长连接，无需公网 URL) vs HTTP 回调 (需要公网 URL)
# ---------------------------------------------------------------------------
# 默认为 Stream 模式（推荐本地 cpolar 环境使用）
STREAM_MODE: bool = os.getenv("DINGTALK_STREAM_MODE", "true").lower() in ("1", "true", "yes", "on")

# ---------------------------------------------------------------------------
# 2. 请假审批模板信息
# ---------------------------------------------------------------------------
# 在钉钉 OA 审批后台创建请假模板后，把 processCode 填到 DINGTALK_LEAVE_PROCESS_CODE
# 例：PROC-2A1B3C4D5E6F-7A8B-9C0D-1E2F-3A4B5C6D7E8F
# 如果为空，审批事件到达时只会打日志"未配置请假模板，跳过"，不会报错
LEAVE_PROCESS_CODE: str = os.getenv("DINGTALK_LEAVE_PROCESS_CODE", "").strip()

# ---------------------------------------------------------------------------
# 3. 审批单表单字段 映射字典
#    key = 我们系统字段名（代码中写死）
#    value = 钉钉 OA 审批模板中对应的表单控件 key / 别名
#
#    提示：如果你创建模板时控件 key 取的名字和默认不同，只要在 .env 里用 JSON 格式写
#         DINGTALK_LEAVE_FIELD_MAP={"leave_type":"我的请假类型控件名"}
# ---------------------------------------------------------------------------
_DEFAULT_FIELD_MAP: Dict[str, str] = {
    # 请假类型：年假/病假/事假/调休/婚假/产假/丧假/其他 -> 对应 LeaveType 枚举
    # 默认按你截图里的模板控件名（中文名「请假类型」）
    "leave_type": "请假类型",
    # 日期区间方式1：单控件 日期区间 (时间段) → "2026-08-05 至 2026-08-07"
    "date_range": "leave_date_range",
    # 日期区间方式2：拆分两个独立日期控件（你截图里的模板就是这种！优先使用）
    # 控件名分别为「开始时间」「结束时间」
    "date_start": "开始时间",
    "date_end": "结束时间",
    # 班段 / 时长：ALL_DAY(全天) / MORNING(上午) / AFTERNOON(下午)
    # 你截图里的模板无此控件，默认全天
    "shift": "shift",
    # 顶岗人 / 替班人员：(控件类型"人员选择")
    # 你刚新增的模板控件名叫「顶岗人」，默认值同步修改
    "replacement_user": "顶岗人",
    # 备注 / 原因：(多行文本)
    # 默认按你截图里的模板控件名「请假事由」
    "note": "请假事由",
}


def _load_field_map_from_env() -> Dict[str, str]:
    """允许用户用 DINGTALK_LEAVE_FIELD_MAP JSON 覆盖默认字段映射"""
    import json
    env_json = os.getenv("DINGTALK_LEAVE_FIELD_MAP", "").strip()
    if not env_json:
        return _DEFAULT_FIELD_MAP.copy()
    try:
        user_map = json.loads(env_json)
        merged = _DEFAULT_FIELD_MAP.copy()
        if isinstance(user_map, dict):
            for k, v in user_map.items():
                if isinstance(k, str) and isinstance(v, str):
                    merged[k] = v
        return merged
    except json.JSONDecodeError:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning("⚠️ DINGTALK_LEAVE_FIELD_MAP JSON 格式解析失败，使用默认字段映射")
        return _DEFAULT_FIELD_MAP.copy()


LEAVE_FIELD_MAP: Dict[str, str] = _load_field_map_from_env()

# ---------------------------------------------------------------------------
# 4. Stream 模式相关配置（一般无需改）
# ---------------------------------------------------------------------------
# Stream 订阅 ID：开发者后台事件订阅页面里生成（如果你在 Stream 里配置了专门的订阅 ID 才填）
# 不填的话用默认订阅通道
STREAM_SUBSCRIPTION_ID: str = os.getenv("DINGTALK_STREAM_SUBSCRIPTION_ID", "").strip()

# 断线自动重连间隔（秒）
STREAM_RECONNECT_INTERVAL: int = int(os.getenv("DINGTALK_STREAM_RECONNECT_INTERVAL", "15"))

# HTTP 回调模式下的签名 token 和 AES_KEY（Stream 模式一般不需要，但为了双模式都支持先留着）
HTTP_CALLBACK_TOKEN: str = os.getenv("DINGTALK_EVENT_TOKEN", "").strip()
HTTP_CALLBACK_AES_KEY: str = os.getenv("DINGTALK_EVENT_AES_KEY", "").strip()
