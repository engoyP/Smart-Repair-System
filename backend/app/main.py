import sys
import os

# 将 backend 目录添加到 Python 搜索路径（确保 app 模块可被找到）
# __file__ = backend/app/main.py → dirname = backend/app → dirname = backend
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 同时支持从项目根目录运行的情况
_project_root = os.path.dirname(_backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from loguru import logger

from app.core.config import settings
from app.api import work_orders, knowledge, devices, spare_parts, users, categories, search, dashboard, dispatch, duty_schedules, leave_requests, notifications
from app.api.work_order_imports import router as work_order_imports_router
from app.api.manual_codes import router as manual_codes_router
from app.api.dingtalk import router as dingtalk_router, ensure_oa_services_started
from app.api.session import router as session_router
from app.api.fault_codes import router as fault_codes_router
from app.api.cascade_data import router as cascade_data_router
from app.api.upload import router as upload_router
from app.api.auth import router as auth_router
from app.api.dingtalk_mock import router as dingtalk_mock_router
from app.mcp.server import mcp_http_app

logger.add(
    settings.LOG_FILE,
    rotation="10 MB",
    retention="30 days",
    level=settings.LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
)

# MCP Server 实例（lifespan 与 mount 复用同一实例）
_mcp_app = mcp_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    logger.info(f"📊 数据库: {settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'N/A'}")
    logger.info(f"🔴 Redis: {settings.REDIS_URL}")
    logger.info(f"🤖 DeepSeek API: {'已配置' if settings.DEEPSEEK_API_KEY else '未配置'}")
    # 预热：探测推理服务（bge-m3 编码 + reranker 重排）是否就绪，不阻塞启动
    try:
        from app.core.embeddings import is_server_available
        from app.core.config import settings as _s
        if is_server_available():
            logger.info(f"🧠 推理服务就绪: {_s.EMBEDDING_SERVER_URL}（{_s.EMBEDDING_MODEL_NAME} + {_s.RERANKER_MODEL_NAME}）")
        else:
            logger.warning(
                f"⚠️ 推理服务不可用: {_s.EMBEDDING_SERVER_URL}。检索将降级为 BM25-only，"
                "请尽快启动推理服务（start_all.ps1 / start_embedding_server.ps1）"
            )
    except Exception as e:
        logger.warning(f"⚠️ 推理服务探测失败: {e}")
    # MCP Server 生命周期（StreamableHTTPSessionManager 任务组初始化）
    async with _mcp_app.lifespan(app):
        yield
    logger.info("👋 应用关闭中...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Smart-Repair-System - 以工单收录与知识沉淀为核心",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(work_orders.router, prefix="/api/v1/work-orders", tags=["工单管理"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["知识管理"])
app.include_router(manual_codes_router, prefix="/api/v1/manual-codes", tags=["设备手册错误码"])
app.include_router(devices.router, prefix="/api/v1/devices", tags=["设备管理"])
app.include_router(spare_parts.router, prefix="/api/v1/spare-parts", tags=["备件管理"])
app.include_router(users.router, prefix="/api/v1/users", tags=["用户管理"])
app.include_router(categories.router, prefix="/api/v1/categories", tags=["分类管理"])
app.include_router(search.router, prefix="/api/v1/search", tags=["知识检索"])
app.include_router(session_router, prefix="/api/v1/session", tags=["会话管理"])
app.include_router(dingtalk_router, prefix="/api/v1/dingtalk", tags=["钉钉集成"])
app.include_router(fault_codes_router, prefix="/api/v1", tags=["故障码映射"])
app.include_router(cascade_data_router, prefix="/api/v1", tags=["级联分类数据"])
app.include_router(upload_router, prefix="/api/v1", tags=["文件上传"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["认证登录"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["数据驾驶舱"])
app.include_router(duty_schedules.router, prefix="/api/v1/duty-schedules", tags=["排班管理"])
app.include_router(leave_requests.router, prefix="/api/v1/leave-requests", tags=["请假申请"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["站内通知"])
app.include_router(dispatch.router, tags=["派工管理"])
app.include_router(dingtalk_mock_router, tags=["钉钉扫码模拟"])
app.include_router(work_order_imports_router, prefix="/api/v1/work-order-imports", tags=["历史工单导入"])

# ============================================================
# MCP Server（Streamable HTTP）：仅本机可访问，可配置 API Key
# ============================================================
_MCP_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def mcp_access_guard(request: Request, call_next):
    """MCP 访问控制：优先 API Key 认证；未配置 Key 时仅允许本机 IP"""
    if request.url.path.startswith("/mcp"):
        if settings.MCP_API_KEY:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {settings.MCP_API_KEY}":
                return JSONResponse(status_code=403, content={"detail": "Forbidden: invalid MCP API key"})
        else:
            client_host = request.client.host if request.client else ""
            if client_host not in _MCP_ALLOWED_HOSTS:
                return JSONResponse(status_code=403, content={"detail": "Forbidden: MCP only accessible from localhost"})
    return await call_next(request)


app.mount("/mcp", _mcp_app, name="mcp")

# ============================================================
# 启动 Stream 客户端 + APScheduler 定时任务（OA审批同步用）
# ============================================================
ensure_oa_services_started(app)

# 静态文件服务 - 上传附件目录
_uploads_dir = os.path.join(_backend_dir, "uploads")
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/api/v1/upload/files", StaticFiles(directory=_uploads_dir), name="upload_files")


# ============================================================
# 前端静态资源托管（SPA）：frontend/dist 构建产物
# 放在所有 API 路由之后挂载，未匹配的路径回落到 index.html（history 路由刷新不 404）
# ============================================================
_frontend_dist = os.path.join(_project_root, "frontend", "dist")


@app.get("/", tags=["系统"], include_in_schema=False)
async def root():
    """根路径：有前端构建产物时返回 SPA 首页，否则返回 API 信息"""
    if os.path.isfile(os.path.join(_frontend_dist, "index.html")):
        from fastapi.responses import FileResponse
        return FileResponse(os.path.join(_frontend_dist, "index.html"))
    return {
        "message": f"欢迎使用 {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "status": "running"
    }


if os.path.isdir(_frontend_dist):
    # assets 等静态资源（js/css/图片）
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dist, "assets")), name="frontend_assets")
else:
    logger.warning(f"⚠️ 前端构建产物不存在: {_frontend_dist}，根路径将返回 API 信息（执行 npm run build 生成）")


@app.get("/health", tags=["系统"])
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "redis": "connected",
        "version": settings.APP_VERSION,
        "mcp": "ok"
    }


if os.path.isdir(_frontend_dist):
    @app.get("/{full_path:path}", tags=["系统"], include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 兜底：非 API/docs/mcp 的未匹配路径统一返回 index.html，支持前端 history 路由"""
        from fastapi.responses import FileResponse
        return FileResponse(os.path.join(_frontend_dist, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.BACKEND_PORT,
        reload=settings.DEBUG
    )