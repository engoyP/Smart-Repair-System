"""智能问答 LangGraph：主图（意图路由）+ 子图（聊天 / 库存 / 故障问答）

架构（与钉钉机器人 RobotGraph 同构：子图作为主图节点挂载）：
- 主图 QaGraph：router 意图分类 → 条件边 → chat / inventory / fault 三个子图节点
- 子图：
  - ChatSubgraph：闲聊/问候/功能介绍，直接回复，不检索（比旧 if-else 少跑一轮无效检索）
  - InventorySubgraph：备件库存查询（复用 AnswerAgent.handle_inventory_query）
  - FaultQaSubgraph：复合故障预检(零 LLM) → 双库检索（知识库 vector+BM25 / 手册错误码精确+语义）→
    RRF 融合 → 严格过滤/加权重排 → 错误码精确置顶

由 /api/v1/search/answer/stream 调用，SSE 事件协议与改造前完全一致：
thinking → (suggest_expert) → references → answer 流式 → done
"""
from __future__ import annotations

from typing import Optional, Any, TypedDict

from loguru import logger
from langgraph.graph import StateGraph, END
from app.core.config import settings


class QaState(TypedDict, total=False):
    question: str
    device_type: Optional[str]
    fault_code: Optional[str]
    top_k: int
    kind: str            # chat | inventory | fault
    payload: Any         # chat:str / inventory:AnswerResult / fault:{cases, error_codes, tools}
    error: str
    suggest_expert: bool  # 复合故障提问 → 提示一键切换专家模式


# ============================================================
# 主图意图路由
# ============================================================
def route_qa_intent(state: QaState) -> str:
    """库存 > 聊天 > 故障问答。判断逻辑与 AnswerAgent 内部保持一致，避免行为漂移。"""
    from app.agents.answer_agent import answer_agent
    q = state.get("question") or ""
    if answer_agent.is_inventory_query(q):
        return "inventory"
    if not answer_agent._is_technical_query(q):
        return "chat"
    return "fault"


# ============================================================
# 子图 1：聊天（问候/功能介绍/闲聊，无检索）
# ============================================================
def chat_node(state: QaState) -> dict:
    from app.agents.answer_agent import answer_agent
    q = state.get("question") or ""
    return {"kind": "chat", "payload": answer_agent._answer_non_technical(q)}


_chat_graph = StateGraph(QaState)
_chat_graph.add_node("chat", chat_node)
_chat_graph.set_entry_point("chat")
_chat_graph.add_edge("chat", END)
CHAT_SUBGRAPH = _chat_graph.compile()


# ============================================================
# 子图 2：库存查询
# ============================================================
def inventory_node(state: QaState) -> dict:
    from app.agents.answer_agent import answer_agent
    from app.core.database import SessionLocal
    q = state.get("question") or ""
    db = SessionLocal()
    try:
        result = answer_agent.handle_inventory_query(q, db)
        return {"kind": "inventory", "payload": result}
    except Exception as e:
        logger.error(f"[QaGraph] 库存查询失败: {e}")
        return {"kind": "inventory", "payload": None, "error": str(e)}
    finally:
        db.close()


_inv_graph = StateGraph(QaState)
_inv_graph.add_node("inventory", inventory_node)
_inv_graph.set_entry_point("inventory")
_inv_graph.add_edge("inventory", END)
INVENTORY_SUBGRAPH = _inv_graph.compile()


# ============================================================
# 子图 3：故障问答（预检 → 双库检索 → 过滤重排 → 错误码置顶）
# ============================================================
def compound_check_node(state: QaState) -> dict:
    """多故障规则预检（连接词 + 多故障信号词，零 LLM 调用）"""
    from app.agents.fault_decomposer import fault_decomposer
    q = state.get("question") or ""
    try:
        if fault_decomposer._looks_compound(q):
            logger.info(f"[QaGraph] 检测到复合故障提问，提示切换专家模式: {q[:50]}")
            return {"suggest_expert": True}
    except Exception as e:
        logger.warning(f"[QaGraph] 多故障检测失败: {e}")
    return {"suggest_expert": False}


def fault_retrieve_node(state: QaState) -> dict:
    """双库检索（公共编排层）：知识库 vector+BM25 + 手册错误码路 → RRF 融合"""
    from app.agents.retrieval_flow import retrieve_hybrid
    q = state.get("question") or ""
    top_k = state.get("top_k") or settings.RECALL_TOP_K
    try:
        merged, error_codes, tools = retrieve_hybrid(
            q, top_k=top_k, device_type=state.get("device_type"),
            fault_code=state.get("fault_code"),
        )
        return {"payload": {"cases": merged, "error_codes": error_codes, "tools": tools}}
    except Exception as e:
        logger.error(f"[QaGraph] 检索阶段失败: {e}")
        return {"payload": {"cases": [], "error_codes": [], "tools": None}}


def fault_filter_node(state: QaState) -> dict:
    """严格过滤 + 加权重排 + 错误码精确置顶（公共编排层）"""
    from app.agents.retrieval_flow import extract_device_and_fault, filter_rerank_cases
    q = state.get("question") or ""
    payload = dict(state.get("payload") or {})
    cases = payload.get("cases") or []
    tools = payload.get("tools")
    error_codes = payload.get("error_codes") or []

    if tools is not None:
        device, kws = extract_device_and_fault(tools, q)
        filtered = filter_rerank_cases(
            tools, cases, q,
            require_device=device, require_keywords=tuple(kws),
            error_codes=error_codes,
        )
    else:
        filtered = [m for m in cases if not m.get("rrf_only", False) and m.get("score", 0) >= settings.RETRIEVAL_COARSE_THRESHOLD][:settings.FINAL_TOP_N]

    payload["cases"] = filtered
    return {"payload": payload}


def fault_verify_node(state: QaState) -> dict:
    """验证 Agent 节点：Gate(客观) → Judge(语义可答性) → 自主重搜 → 存在性核对(查库)

    输出 verified_cases（唯一允许进入回答阶段的信息源），杜绝回答胡编乱造。
    """
    from app.agents.verify_agent import verify_agent
    q = state.get("question") or ""
    payload = dict(state.get("payload") or {})
    cases = payload.get("cases") or []
    error_codes = payload.get("error_codes") or []
    try:
        verified, report = verify_agent.verify(
            q, cases,
            device_type=state.get("device_type"),
            error_codes=error_codes,
        )
        payload["cases"] = verified
        payload["verify_report"] = report
    except Exception as e:
        logger.error(f"[QaGraph] 验证 Agent 执行失败，使用原始候选: {e}")
    return {"payload": payload}


_fault_graph = StateGraph(QaState)
_fault_graph.add_node("compound_check", compound_check_node)
_fault_graph.add_node("retrieve", fault_retrieve_node)
_fault_graph.add_node("filter", fault_filter_node)
_fault_graph.add_node("verify", fault_verify_node)
_fault_graph.set_entry_point("compound_check")
_fault_graph.add_edge("compound_check", "retrieve")
_fault_graph.add_edge("retrieve", "filter")
_fault_graph.add_edge("filter", "verify")
_fault_graph.add_edge("verify", END)
FAULT_SUBGRAPH = _fault_graph.compile()


# ============================================================
# 主图构建
# ============================================================
def build_qa_graph():
    graph = StateGraph(QaState)
    graph.add_node("router", lambda s: {})  # 占位节点，实际分发由条件边完成
    graph.add_node("chat", CHAT_SUBGRAPH)
    graph.add_node("inventory", INVENTORY_SUBGRAPH)
    graph.add_node("fault", FAULT_SUBGRAPH)
    graph.set_entry_point("router")
    graph.add_conditional_edges(
        "router",
        route_qa_intent,
        {"chat": "chat", "inventory": "inventory", "fault": "fault"},
    )
    for n in ("chat", "inventory", "fault"):
        graph.add_edge(n, END)
    return graph.compile()


QA_GRAPH = build_qa_graph()


def invoke_qa(
    question: str,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    top_k: int = 10,
) -> QaState:
    """智能问答入口：执行主图 + 子图，返回最终 state（kind 指明走了哪个子图）"""
    return QA_GRAPH.invoke({
        "question": question,
        "device_type": device_type,
        "fault_code": fault_code,
        "top_k": top_k,
    })
