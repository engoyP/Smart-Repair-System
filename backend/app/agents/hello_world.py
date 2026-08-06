from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict
import os
from app.core.config import settings

router = APIRouter()

class ChatState(TypedDict):
    messages: List[dict]
    user_input: str
    response: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[dict]] = []

class ChatResponse(BaseModel):
    response: str
    status: str

def create_agent():
    if not settings.DEEPSEEK_API_KEY:
        return None

    llm = ChatOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        model=settings.DEEPSEEK_MODEL,
        temperature=0.7,
        streaming=False
    )
    return llm

def agent_node(state: ChatState) -> ChatState:
    llm = create_agent()
    if not llm:
        state["response"] = "错误：DeepSeek API Key 未配置，请检查环境变量 DEEPSEEK_API_KEY"
        return state

    messages = [SystemMessage(content="你是一个企业维修知识管理系统的 AI 助手，专注于帮助用户解决设备维修问题。请用简洁专业的中文回答。")]

    for msg in state["messages"][-5:]:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=state["user_input"]))

    try:
        response = llm.invoke(messages)
        state["response"] = response.content
        state["messages"].append({"role": "user", "content": state["user_input"]})
        state["messages"].append({"role": "assistant", "content": response.content})
    except Exception as e:
        state["response"] = f"调用 LLM 失败：{str(e)}"

    return state

workflow = StateGraph(ChatState)
workflow.add_node("agent", agent_node)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)
agent_executor = workflow.compile()

@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(request: ChatRequest):
    try:
        initial_state = {
            "messages": request.conversation_history or [],
            "user_input": request.message,
            "response": ""
        }

        result = agent_executor.invoke(initial_state)

        return ChatResponse(
            response=result["response"],
            status="success"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 执行失败：{str(e)}")

@router.post("/hello-world")
async def hello_world():
    if not settings.DEEPSEEK_API_KEY:
        return {
            "status": "error",
            "message": "请先配置 DEEPSEEK_API_KEY 环境变量",
            "hint": "1. 访问 https://platform.deepseek.com 注册账号\n2. 获取 API Key\n3. 在 .env 文件中设置 DEEPSEEK_API_KEY=your_api_key"
        }

    try:
        llm = create_agent()
        response = llm.invoke([HumanMessage(content="你好！请简单介绍一下你自己，并说明你能为企业维修知识管理系统提供什么帮助。")])

        return {
            "status": "success",
            "message": "LangChain + LangGraph Agent 运行成功！",
            "llm_response": response.content,
            "model": settings.DEEPSEEK_MODEL,
            "provider": "DeepSeek"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Agent 运行失败：{str(e)}",
            "hint": "请检查 DeepSeek API Key 是否有效，以及网络连接是否正常"
        }


@router.get("/milvus-health")
async def milvus_health():
    """检查 Milvus 向量数据库连接状态"""
    try:
        from app.core.vector_store import vector_store
        count = vector_store.count()
        return {
            "status": "success",
            "message": "Milvus 向量数据库连接正常",
            "collection": settings.MILVUS_COLLECTION,
            "vector_size": settings.MILVUS_VECTOR_SIZE,
            "total_vectors": count,
            "host": settings.MILVUS_HOST,
            "port": settings.MILVUS_PORT
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Milvus 连接失败：{str(e)}",
            "hint": "请确认 Milvus 服务已启动：docker-compose -f docker-compose.dev.yml up -d milvus"
        }


@router.post("/milvus-test")
async def milvus_test():
    """测试 Milvus 向量存储的增删查改"""
    try:
        from app.core.vector_store import vector_store

        # 1. 插入测试向量（随机生成，实际应使用 Embedding 模型）
        import random
        test_vector = [random.uniform(-1, 1) for _ in range(settings.MILVUS_VECTOR_SIZE)]

        point_id = vector_store.insert(
            vector=test_vector,
            knowledge_id=9999,
            title="测试知识条目",
            content="这是一条测试知识，关于注塑机温度偏高的故障排查",
            device_type="注塑机",
            fault_code="TEMP_HIGH_001",
            fault_tags=["温度", "报警", "注塑机"]
        )

        # 2. 搜索测试
        search_results = vector_store.search(
            query_vector=test_vector,
            limit=3,
            score_threshold=0.3
        )

        # 3. 获取总数
        total = vector_store.count()

        # 4. 获取详情
        detail = vector_store.get_by_id(point_id)

        # 5. 删除测试数据
        vector_store.delete(point_id)

        return {
            "status": "success",
            "message": "Milvus 向量存储测试通过！",
            "insert": {"point_id": point_id, "vector_size": len(test_vector)},
            "search_results": len(search_results),
            "total_vectors": total,
            "detail": "获取成功" if detail else "获取失败",
            "delete": "success"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Milvus 测试失败：{str(e)}",
            "hint": "请确认 Milvus 服务已启动"
        }