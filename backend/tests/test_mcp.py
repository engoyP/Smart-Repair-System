"""MCP Server 工具调用测试（需后端运行在 127.0.0.1:8000）

验证：MCP 协议握手、工具清单、9 个工具 tools/call 输入输出、多轮调用隔离。
"""
import httpx
import pytest

BASE = "http://127.0.0.1:8000/mcp"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

EXPECTED_TOOLS = {
    "search_knowledge",
    "guided_repair_chat",
    "query_work_order",
    "query_my_workorders",
    "query_inventory",
    "get_user_by_staff",
    "get_device_list",
    "get_knowledge_stats",
    "get_workorder_stats",
}


def _rpc(method, params=None, msg_id=1, timeout=30.0):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return httpx.post(BASE, json=body, headers=HEADERS, timeout=timeout, follow_redirects=True)


@pytest.fixture(scope="module")
def session():
    r = _rpc("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1.0"},
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "result" in data, data
    _rpc("notifications/initialized")
    return data


def test_initialize(session):
    assert "serverInfo" in session["result"]
    assert session["result"]["serverInfo"]["name"]


def test_tools_list(session):
    r = _rpc("tools/list", {}, msg_id=2)
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == EXPECTED_TOOLS, f"工具清单不一致: {names}"


def _call(name, args, timeout=60.0):
    r = _rpc("tools/call", {"name": name, "arguments": args}, timeout=timeout)
    assert r.status_code == 200, r.text
    result = r.json().get("result", {})
    content = result.get("content", [])
    text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
    return result, text


def test_query_work_order(session):
    result, text = _call("query_work_order", {"work_order_no": "WO-20260804-002"})
    assert not result.get("isError"), text
    assert "WO-20260804-002" in text


def test_query_my_workorders(session):
    result, text = _call("query_my_workorders", {"staff_id": "480161596224178906"})
    assert not result.get("isError"), text
    assert text.strip()


def test_query_inventory(session):
    result, text = _call("query_inventory", {"question": "查一下保险丝的库存"})
    assert not result.get("isError"), text
    assert text.strip()


def test_get_user_by_staff(session):
    result, text = _call("get_user_by_staff", {"staff_id": "480161596224178906"})
    assert not result.get("isError"), text
    assert text.strip()


def test_get_device_list(session):
    result, text = _call("get_device_list", {"keyword": ""})
    assert not result.get("isError"), text
    assert text.strip()


def test_get_knowledge_stats(session):
    result, text = _call("get_knowledge_stats", {})
    assert not result.get("isError"), text
    assert "知识库统计" in text


def test_get_workorder_stats(session):
    result, text = _call("get_workorder_stats", {})
    assert not result.get("isError"), text
    assert "工单统计" in text


def test_search_knowledge(session):
    result, text = _call("search_knowledge", {"query": "注塑机 温度过高"}, timeout=90.0)
    assert not result.get("isError"), text
    assert text.strip(), "知识检索返回为空"


def test_guided_repair_chat(session):
    """追踪维修：首次故障描述返回【分析】+【操作】引导式回复"""
    result, text = _call("guided_repair_chat",
                         {"staff_id": "pytest_staff", "message": "PLC输入输出通道无响应，指示灯异常"},
                         timeout=90.0)
    assert not result.get("isError"), text
    assert text.strip(), "追踪维修返回为空"
    assert "【操作】" in text or "【分析】" in text, f"应包含分析/操作引导: {text[:200]}"


def test_multi_call_session_isolation(session):
    """多轮调用无状态泄漏：连续多次调用不同工具均正常"""
    for name, args in [
        ("get_knowledge_stats", {}),
        ("get_workorder_stats", {}),
        ("get_knowledge_stats", {}),
    ]:
        result, text = _call(name, args)
        assert not result.get("isError"), text
