"""MCP Server：将系统能力暴露为标准 MCP 工具（Streamable HTTP）

- 工具实现复用 app/mcp/tools.py（与钉钉机器人同一来源）
- 智能工具（LLM 调用）用 asyncio.to_thread 放入线程池并加超时，避免阻塞事件循环
- main.py 通过 mcp_http_app() 挂载到 FastAPI /mcp 路径
"""
from __future__ import annotations

import asyncio

from fastmcp import FastMCP
from loguru import logger

from app.mcp import tools

mcp = FastMCP("维知工智维修知识管理系统")

# 智能工具超时上限（LLM 生成较慢）
SMART_TIMEOUT = 25.0   # search_knowledge：混合检索 + AnswerAgent
INVENTORY_TIMEOUT = 15.0  # query_inventory：库存解析


async def _call(fn, timeout: float, *args, **kwargs):
    """将同步工具函数放入线程池执行，并加超时保护"""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"[MCP] 工具 {getattr(fn, '__name__', '?')} 执行超时（{timeout}s）")
        return "处理超时，请稍后再试。"


@mcp.tool()
async def search_knowledge(query: str) -> str:
    """输入设备故障描述（如"注塑机 温度过高"），检索历史维修案例并生成分析回答。可能耗时数秒至十几秒。"""
    return await _call(tools.search_knowledge, SMART_TIMEOUT, query)


@mcp.tool()
async def guided_repair_chat(staff_id: str, message: str) -> str:
    """追踪维修模式：按钉钉企业 userId 维护多轮会话，逐步引导维修员排查故障，每轮只给出一步【分析】+【操作】。输入用户最近发送的故障现象或上一步检查结果。可能耗时数秒至十几秒。"""
    return await _call(tools.guided_repair_chat, SMART_TIMEOUT, staff_id, message)


@mcp.tool()
async def query_work_order(work_order_no: str) -> str:
    """按工单号（如 WO-20260804-002）查询工单状态、设备、维修员和最新进度。"""
    return await _call(tools.query_work_order, 10.0, work_order_no)


@mcp.tool()
async def query_my_workorders(staff_id: str) -> str:
    """按钉钉企业 userId（senderStaffId）查询该用户名下待处理工单列表。"""
    return await _call(tools.query_my_workorders, 10.0, staff_id)


@mcp.tool()
async def query_inventory(question: str) -> str:
    """输入备件问题（如"查一下保险丝的库存"），返回备件库存、安全库存与状态。可能耗时数秒。"""
    return await _call(tools.query_inventory, INVENTORY_TIMEOUT, question)


@mcp.tool()
async def get_user_by_staff(staff_id: str) -> str:
    """按钉钉企业 userId 查询系统用户的绑定信息（姓名/手机/角色/部门）。"""
    return await _call(tools.get_user_by_staff, 10.0, staff_id)


@mcp.tool()
async def get_device_list(keyword: str = "") -> str:
    """查询设备列表，可按关键字（名称/编码/类型）过滤。"""
    return await _call(tools.get_device_list, 10.0, keyword)


@mcp.tool()
async def get_knowledge_stats() -> str:
    """查询知识库条目统计（总量/已发布/草稿/审核中）。"""
    return await _call(tools.get_knowledge_stats, 10.0)


@mcp.tool()
async def get_workorder_stats() -> str:
    """查询工单统计（总量/进行中/已完成）。"""
    return await _call(tools.get_workorder_stats, 10.0)


def mcp_http_app():
    """返回可挂载到 FastAPI 的 Starlette app

    内部路由固定在根路径（path="/"），由 FastAPI app.mount("/mcp", ...) 决定
    对外访问路径为 /mcp；json_response=True 使响应为 JSON（便于外部客户端与测试）。
    """
    return mcp.http_app(path="/", transport="streamable-http", stateless_http=True, json_response=True)
