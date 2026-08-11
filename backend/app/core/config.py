from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path

# .env 文件绝对路径：backend/.env
_ENV_FILE = str(Path(__file__).resolve().parent.parent.parent / ".env")


class Settings(BaseSettings):
    # 强制用绝对路径加载 .env，避免相对路径依赖 CWD 导致 uvicorn worker 读取不到配置
    model_config = SettingsConfigDict(env_file=_ENV_FILE, case_sensitive=True, extra="ignore")
    # 应用配置
    APP_NAME: str = "Smart-Repair-System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    BACKEND_PORT: int = 18080

    # 数据库配置
    DB_USER: str = "admin"
    DB_PASSWORD: str = "admin123"
    DB_NAME: str = "maintenance_db"
    DB_HOST: str = "localhost"
    DB_PORT: int = 15432
    DATABASE_URL: str = ""

    # Redis 配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_URL: str = ""

    # Milvus 向量数据库配置
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_REST_PORT: int = 9091
    MILVUS_COLLECTION: str = "knowledge"
    MILVUS_LOG_CODE_COLLECTION: str = "log_code"  # 设备手册错误码向量集合
    MILVUS_VECTOR_SIZE: int = 1024  # Embedding 维度 (Qwen3-0.6B hidden_size=1024)
    MINIO_HOST: str = "localhost"
    MINIO_PORT: int = 9000
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"

    # DeepSeek API 配置
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # 钉钉开放平台配置
    DINGTALK_APP_KEY: str = ""
    DINGTALK_APP_SECRET: str = ""
    DINGTALK_AGENT_ID: str = ""
    DINGTALK_CORP_ID: str = ""
    DINGTALK_ROBOT_CODE: str = ""  # 企业内部机器人 RobotCode（单聊消息回复用）
    DINGTALK_API_TOKEN: str = ""  # 直接使用 API Token（跳过 AppKey/AppSecret 换 token）
    DINGTALK_REDIRECT_URI: str = "http://localhost:8000/api/v1/dingtalk/callback"
    DINGTALK_MOCK_MODE: bool = True  # Mock 模式：钉钉 API 不可用时使用模拟数据

    # 阿里云短信服务配置
    SMS_ACCESS_KEY_ID: str = ""
    SMS_ACCESS_KEY_SECRET: str = ""
    SMS_SIGN_NAME: str = ""          # 短信签名（需在阿里云短信控制台申请）
    SMS_TEMPLATE_CODE: str = ""      # 验证码短信模板 CODE（需在阿里云短信控制台申请）
    SMS_ENABLED: bool = False        # 是否启用真实短信发送

    # 服务器公开访问地址（用于生成可扫码的真实 URL）
    SERVER_PUBLIC_URL: str = "http://127.0.0.1:8000"

    # JWT 配置
    SECRET_KEY: str = "your-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"

    # 追踪后端选择：ragflow | langfuse | local
    TRACING_BACKEND: str = "ragflow"

    # RAGFlow 追踪配置
    RAGFLOW_HOST: str = "http://localhost:9380"
    RAGFLOW_API_KEY: str = ""
    RAGFLOW_TRACES_DATASET: str = "ticket_traces"
    RAGFLOW_ENABLED: bool = True

    # LangFuse 追踪配置（保留兼容）
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_ENABLED: bool = False

    # MCP 服务配置
    MCP_API_KEY: str = ""  # MCP 认证密钥（配置后要求 Authorization: Bearer <key>，未配置则仅允许本机 IP）

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.DATABASE_URL:
            self.DATABASE_URL = f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        if not self.REDIS_URL:
            redis_auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
            self.REDIS_URL = f"redis://{redis_auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        if self.SERVER_PUBLIC_URL == "http://127.0.0.1:8000":
            self.SERVER_PUBLIC_URL = self._detect_public_url()

    def _detect_public_url(self) -> str:
        """自动检测本机局域网 IP，用于生成可扫码的 URL"""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return f"http://{ip}:{self.BACKEND_PORT}"
        except Exception:
            return f"http://127.0.0.1:{self.BACKEND_PORT}"

    @property
    def milvus_connection(self) -> str:
        return f"{self.MILVUS_HOST}:{self.MILVUS_PORT}"


settings = Settings()