# Smart-Repair-System · 智能维修系统

面向制造企业的**智能维修知识沉淀与诊断平台**。核心目标：把老师傅的维修经验沉淀成结构化工单和知识库，让新人在遇到设备故障时通过自然语言提问，AI 检索历史案例并给出诊断建议。

```
维修工单 ──→ 知识抽取与去重 ──→ 知识库（PostgreSQL + Milvus 向量）
                                        ↑
新人提问 ──→ 混合检索（向量 + BM25 + 手册错误码）──→ RRF 融合 ──→ 验证 Agent ──→ AI 诊断回答
```

## 核心特性

| 能力 | 说明 |
|------|------|
| 工单全生命周期 | 14 态状态机（DRAFT → ARCHIVED/REJECTED），每次流转全程留痕 |
| 知识库 RAG 检索 | Milvus 向量 + PostgreSQL BM25 双库最多四路召回，RRF 名次融合 + 加权重排 + 错误码置顶 |
| 设备手册错误码库 | 错误码精确 + 语义双路检索，权威处理方案置顶 |
| AI 分析型问答 | LangGraph 主图意图路由（库存 > 聊天 > 故障）+ 三子图，五段式结构化回答 + SSE 流式 |
| 验证 Agent | Gate + Judge + 存在性核对三层把关 + 自主重搜循环，把"不编造"升级为机制保障 |
| 专家模式 | 复合故障拆解（规则预检 + LLM）→ 并行 ReAct 检索 → 按故障分组流式回答 |
| 引导式追踪维修 | LangGraph 对话状态机 + Redis 会话（24h TTL），逐层排查引导 |
| 钉钉企业集成 | OAuth 登录、机器人对话（LangGraph 意图路由）、OA 审批同步、工单卡片推送 |
| 备件 / 排班 / 派工 | 库存预警、排班事务联动、派工看板、数据驾驶舱 |

## 技术栈

| 层 | 技术 |
|------|------|
| 后端 | FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 |
| AI / LLM | LangChain · LangGraph · DeepSeek（deepseek-chat）· LangFuse 追踪 |
| Embedding | Qwen3-Embedding-0.6B（本地推理，1024 维，EOS hidden state + L2 归一化） |
| 数据存储 | PostgreSQL 16（业务 + BM25）· Milvus 2.4（IVF_FLAT + COSINE）· Redis 7 · MinIO · etcd |
| 前端 | Vue 3 · Vite · Pinia · Element Plus |
| 集成 | 钉钉开放平台（OAuth / Stream 长连接 / OA 审批）· cpolar 内网穿透 |

## 架构

```
┌─────────────────────────────────────────────┐
│  前端 Vue3 + Vite（Port 4173）               │
│  维修报表 / 知识库 / AI问答 / 驾驶舱 / 库存  │
└────────────────────┬────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────┐
│  FastAPI 后端（Port 18080）                  │
│  ┌──────────────────────────────────────┐   │
│  │ Agent 层                              │   │
│  │  QA_GRAPH(主图+3子图) · AnswerAgent   │   │
│  │  GuidedRepair · TicketAgent          │   │
│  │  RobotGraph(钉钉) · FaultDecomposer  │   │
│  │  VerifyAgent(验证) · ReAct 检索 Agent │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │ 公共检索编排层 retrieval_flow.py      │   │
│  │ 双库召回 → RRF 融合 → 过滤重排 → 置顶  │   │
│  └──────────────────────────────────────┘   │
└──────┬───────────┬───────────┬──────────────┘
       │           │           │
┌──────▼──┐  ┌─────▼────┐  ┌───▼─────┐
│PostgreSQL│  │  Milvus  │  │  Redis  │
│ 业务+BM25 │  │  向量库   │  │ 会话/缓存│
└─────────┘  └──────────┘  └─────────┘
```

## 快速开始

**前置**：Docker、Python 3.x、Node.js 18+；`backend/.env` 需配置 DeepSeek / 钉钉密钥（参考 `backend/.env.example`）。

### 一键启动（Windows）

```powershell
# 先打开 Docker Desktop，然后：
.\start_all.ps1
```

脚本自动完成：端口体检（冲突自动修复）→ `docker compose up -d` → 后台启动后端（18080）+ 前端（4173）。

### 手动启动

```powershell
# ① 基础设施（PostgreSQL / Redis / Milvus / MinIO / etcd）
cd Smart-Repair-System
docker compose up -d

# ② 后端
cd backend
pip install -r ..\requirements.txt   # 首次
alembic upgrade head                 # 初始化数据库表结构（首次）
python scripts\seed_knowledge.py     # 导入种子知识（首次）
python scripts\seed_data.py          # 导入基础数据（首次）
uvicorn app.main:app --host 0.0.0.0 --port 18080

# ③ 前端（另开终端）
cd frontend
npm install                          # 首次
npm run dev                          # Port 4173，代理 /api → 18080
```

访问：前端 http://127.0.0.1:4173 · 后端 Swagger http://127.0.0.1:18080/docs

> 端口约定：后端 **18080**、前端 **4173**、PG **15432**、Redis **7379**、Milvus **19530**。

## 项目结构

```
├── backend/               # FastAPI 后端
│   ├── app/agents/        # Agent 层（QA_GRAPH / VerifyAgent / FaultDecomposer / ReAct 等）
│   ├── app/api/           # 路由层（21 个 prefix）
│   ├── app/core/          # 基础设施（数据库 / 向量 / Embedding / 钉钉 / LangFuse）
│   ├── app/models/        # SQLAlchemy 模型
│   ├── alembic/           # 数据库迁移
│   └── scripts/           # 种子数据 / 导入脚本
├── frontend/              # Vue3 + Vite 前端
├── docker-compose.yml     # 中间件编排
├── requirements.txt       # Python 依赖
└── 项目说明/               # 详细文档（操作指南 / 检索机制 / RRF 融合 / 面试指南）
```

## 检索策略（召回 → 融合 → 过滤 → 验证）

1. **召回**：知识库向量 + BM25 双路；问题含错误码时增开手册库精确 + 语义两路
2. **融合**：RRF 名次融合（`Σ 1/(60+rank)`），复合去重键防双库撞号
3. **过滤**：0.15 粗滤 + 加权重排 + 设备/故障关键词严格过滤 + 错误码置顶
4. **验证**：验证 Agent 三层把关（Gate / Judge / 存在性核对）+ 自主重搜循环

详见 [项目说明/检索调优路线.md](项目说明/检索调优路线.md)。

## 文档

| 文档 | 内容 |
|------|------|
| [操作指南](项目说明/PROJECT_GUIDE.md) | Docker / 启动流程 / Git 使用 / 常见问题排查 |
| [RRF 融合算法详解](项目说明/RRF融合算法详解.md) | RRF 原理、去重键、双库四路融合 |
| [ReAct 循环检索详解](项目说明/REACT_RETRIEVAL.md) | ReAct 检索 Agent 设计 |
| [检索机制详解](项目说明/RETRIEVAL_PIPELINE.md) | 检索链路上下游 |
| [面试学习指南](项目说明/Smart-Repair-System%20面试学习指南.md) | 架构原理与高频面试问答 |
