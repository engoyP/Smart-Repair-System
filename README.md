# Smart-Repair-System · 智能维修系统

面向制造企业的**设备维修数字化平台**，核心目标是把老师傅的维修经验沉淀为结构化工单和知识库，让维修人员通过自然语言提问即可检索历史案例、设备手册错误码和诊断建议。

```
维修工单/历史工单 ──→ 知识抽取、去重、人工审核 ──→ 知识库
                                      │
新人提问 ──→ 意图路由 ──→ 混合检索（向量 + BM25 + 手册错误码）
                                      │
                          RRF 融合 → 过滤 → Reranker 精排 → 验证 Agent → AI 诊断回答
```

## 一、核心能力

| 能力 | 说明 |
| --- | --- |
| 工单全生命周期 | 14 态状态机，从 DRAFT 到 ARCHIVED/REJECTED，每次流转写入进度日志 |
| 设备台账与监控 | 设备档案、运行状态、心跳、故障标签、外部监控系统同步接口 |
| 知识库 RAG | PostgreSQL BM25 + Milvus 向量双路召回，RRF 名次融合，两级模型精排 |
| 设备手册错误码库 | 说明书错误码结构化入库，精确匹配 + 语义双路检索，权威方案置顶 |
| AI 智能问答 | LangGraph 主图意图路由（库存 > 聊天 > 故障），SSE 流式回答 |
| 追踪维修 | LangGraph 多轮对话状态机，按“分析 + 操作”逐步引导排查 |
| 专家模式 | 复合故障拆解，并行 ReAct 检索，按故障分组流式回答 |
| 验证 Agent | Gate、Judge、存在性核对三层把关，支持自主重搜 |
| 知识审核与去重 | DRAFT/UNDER_REVIEW/PUBLISHED/DEPRECATED/ARCHIVED 状态，LLM 去重检测 |
| 备件库存 | 备件台账、安全库存、库存预警、进货单批量导入 |
| 排班 / 请假 / 派工 | 班次排班、请假申请与审批、顶岗人、工单冲突预检、主管派工 |
| 数据驾驶舱 | 工单、设备、知识、备件等聚合统计看板 |
| 钉钉集成 | 扫码登录、OAuth、机器人对话、OA 审批、工单卡片、通讯录同步 |
| 历史工单导入 | PDF 上传，LangGraph 流水线抽取，人工确认后写入工单并收录知识 |
| MCP 服务 | 通过 `/mcp` 向外部 AI 客户端暴露知识检索、工单、库存、设备等工具 |

## 二、技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3、Vite、Pinia、Element Plus、Vue Router、Axios |
| 后端 | FastAPI、SQLAlchemy 2.0、Alembic、Pydantic v2、Loguru |
| AI / Agent | LangChain、LangGraph、FastMCP、DeepSeek、RAGFlow/LangFuse/local 追踪 |
| 召回 / 精排 | bge-m3 召回（1024 维）、Qwen3-Reranker-0.6B 精排 |
| 数据存储 | PostgreSQL 16、Redis 7、Milvus 2.4、MinIO、etcd |
| 集成 | 钉钉开放平台、阿里云短信、RAGFlow |
| 测试 | Pytest、pytest-asyncio、pytest-cov |

## 三、系统架构

```text
┌────────────────────────────────────────────┐
│ Vue 3 + Vite 前端（Port 4173）              │
│ 驾驶舱/工单/设备/知识/手册/库存/搜索/AI/排班 │
└────────────────────┬───────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼───────────────────────┐
│ FastAPI 后端（Port 18080）                  │
│ API 层：21 个路由模块，另挂载 MCP             │
│ Agent 层：QA Graph、追踪维修、专家模式、      │
│ 验证 Agent、工单导入、钉钉机器人、ReAct       │
│ 公共检索编排层：retrieval_flow.py           │
└──────┬──────────┬──────────┬───────────────┘
       │          │          │
 PostgreSQL    Milvus      Redis
 业务+BM25     向量库      会话/缓存
```

核心服务：

| 服务 | 本机端口 | 说明 |
| --- | --- | --- |
| PostgreSQL | 15432 | 业务数据、BM25 检索 |
| Redis | 7379 | 会话、缓存、追踪维修会话 |
| etcd | 2379 | Milvus 元数据 |
| MinIO | 9000 / 9001 | Milvus 依赖的对象存储 |
| Milvus | 19530 / 9091 | 知识向量、手册错误码向量 |
| Attu | 8080 | Milvus Web 管理界面 |
| 统一推理服务 | 8010 | bge-m3 编码 + Qwen3-Reranker 精排 |
| 后端 API | 18080 | FastAPI，Swagger 在 `/docs` |
| 前端开发服务器 | 4173 | Vite，代理 `/api` 和 `/dingtalk` 到 18080 |

> `docker-compose.yml` 是 RAGFlow 编排，核心开发基础设施使用 `docker-compose.dev.yml`。根目录 `.env` 用于 Docker 和 RAGFlow 插值，后端业务配置在 `backend/.env`。

## 四、目录结构

```text
Smart-Repair-System/
├── backend/
│   ├── app/
│   │   ├── agents/            # QA 图、追踪维修、专家模式、验证、检索、工单导入等
│   │   ├── api/               # FastAPI 路由模块
│   │   ├── core/              # 配置、数据库、缓存、向量、推理服务、钉钉、短信、通知
│   │   ├── mcp/               # MCP Server 与业务工具
│   │   └── models/            # SQLAlchemy 模型
│   ├── alembic/versions/      # 数据库迁移
│   ├── scripts/               # 种子数据、向量同步、手册导入、阈值校准
│   ├── tests/                 # 单元测试
│   ├── .env / .env.example
│   └── Dockerfile
├── frontend/
│   ├── src/api/               # 前后端接口封装
│   ├── src/layouts/           # PC 端与移动端布局
│   ├── src/router/            # 路由
│   ├── src/styles/            # 全局样式
│   └── src/views/             # 页面
├── docker-compose.dev.yml     # 开发基础设施：PG/Redis/Milvus/etcd/MinIO/Attu
├── docker-compose.yml         # RAGFlow 编排（可选）
├── requirements.txt           # Python 依赖
├── setup.ps1                  # 一键初始化
├── start_all.ps1              # 一键启动
├── start_embedding_server.ps1 # 单独启动推理服务
└── 项目说明/                  # 操作指南、检索链路、面试学习指南
```

### 后端核心目录

- `app/agents`：`qa_graph.py`、`guided_repair_agent.py`、`expert_repair_agent.py`、`verify_agent.py`、`retrieval_flow.py`、`retrieval_agent.py`、`fault_decomposer.py`、`answer_agent.py`、`manual_structurizer.py`、`knowledge_extractor.py`、`dedup_agent.py`、`ticket_agent.py`、`robot_graph.py`、`work_order_importer.py`、`session_agent.py`、`inventory_tools.py`、`tools.py`
- `app/api`：认证、用户、设备、工单、工单导入、知识、手册错误码、备件、分类、故障码、搜索、会话、驾驶舱、排班、请假、通知、派工、钉钉、文件上传、级联数据
- `app/core`：`embedding_server.py`、`embeddings.py`、`reranker.py`、`vector_store.py`、`cache_service.py`、`database.py`、`config.py`、`security.py`、`dingtalk*.py`、`robot_handler.py`、`notification.py`、`sms.py`、`stock_alert.py`、`sys_config.py`、`manual_text.py`、`langfuse_tracer.py`
- `app/models`：用户、设备、工单、进度日志、知识、手册错误码、故障码映射、分类、备件、排班、请假、通知、系统配置、工单导入批次与明细

### 前端主要页面

- PC 端：数据驾驶舱、维修报表、工单新建/详情、设备列表/表单、知识库/知识表单、设备手册、故障码、库存、仓库、搜索、AI 问答、用户、分类、导入、个人设置、账号安全、帮助、主管派工、实时进度、排班管理
- 移动端 `/m`：故障上报、我的工单、工单详情

## 五、初始化与启动

### 前置条件

- Docker Desktop
- Python 3.10+
- Node.js 18+
- `backend/.env` 配置 `DEEPSEEK_API_KEY`

### 一键初始化

```powershell
.\setup.ps1
```

脚本会完成：Docker 基础设施启动、后端虚拟环境与依赖安装、`backend/.env` 检查、Alembic 迁移、种子数据导入、知识向量同步、前端 `npm install`。也可以按需跳过：

```powershell
.\setup.ps1 -SkipInfra
.\setup.ps1 -SkipBackend
.\setup.ps1 -SkipFrontend
.\setup.ps1 -SkipDB
```

### 一键启动

```powershell
.\start_all.ps1
```

该脚本会检查 Hyper-V/WSL 保留端口冲突，启动开发基础设施、统一推理服务、后端和前端，并轮询推理服务 `/health` 就绪。

### 手动启动

```powershell
# 1. 启动基础设施
docker compose -f docker-compose.dev.yml up -d

# 2. 启动推理服务（bge-m3 + Qwen3-Reranker，CPU 加载约 3-6 分钟）
cd backend
python -m app.core.embedding_server --host 0.0.0.0 --port 8010

# 3. 初始化数据库（首次）
alembic upgrade head
python scripts\seed_knowledge.py
python scripts\seed_categories.py
python scripts\seed_fault_codes.py
python scripts\seed_data.py
python scripts\import_manual_codes.py   # 可选：导入设备手册错误码
python scripts\sync_vectors.py          # 知识条目同步到 Milvus

# 4. 启动后端
uvicorn app.main:app --host 0.0.0.0 --port 18080

# 5. 另开终端启动前端
cd ..\frontend
npm install
npm run dev
```

访问地址：

- 前端：<http://127.0.0.1:4173>
- 后端 Swagger：<http://127.0.0.1:18080/docs>
- 健康检查：<http://127.0.0.1:18080/health>
- 推理服务健康检查：<http://127.0.0.1:8010/health>

## 六、AI 问答与检索链路

### 检索策略

1. 召回：知识库向量 + BM25 双路；问题含错误码时增加手册错误码精确 + 语义两路
2. 融合：RRF 名次融合，复合去重键防止双库撞号
3. 过滤：向量相似度粗筛 + 设备类型 / 故障关键词严格过滤
4. 精排：Qwen3-Reranker-0.6B 对候选集打分；不可用时回退规则重排
5. 置顶：手册错误码精确命中结果优先
6. 验证：验证 Agent 把关后进入回答阶段

### 降级策略

- 推理服务不可用：检索自动降级为 BM25-only，跳过向量分数阈值
- Reranker 不可用：回退 `weighted_rerank` 规则重排
- 严格过滤为空：回退宽松过滤 Top 2，避免误伤导致“未检索到”

### AI 模式

| 模式 | 入口 | 说明 |
| --- | --- | --- |
| 智能问答 | `/api/v1/search/answer/stream` | LangGraph 意图路由：库存 > 聊天 > 故障 |
| 追踪维修 | `/api/v1/search/guided-repair/*` | 多轮逐步排查，Redis 会话持久化 |
| 专家模式 | `/api/v1/search/answer/expert` | 复合故障拆解 + ReAct 检索 + 流式回答 |
| 专家模式下一步 | `/api/v1/search/answer/expert/step` | 多轮分析 + 引导 |
| 混合检索 | `/api/v1/search/hybrid` | 无 Agent 的检索链路 |
| Agent 检索 | `/api/v1/search/agent` | ReAct 循环检索 |
| 快速检索 | `/api/v1/search/quick` | 快速语义检索 |

## 七、设备手册错误码

手册错误码使用独立模型 `ManualCodeEntry`，与知识库职责分离：

- 知识库：历史维修工单沉淀的真实案例
- 手册库：设备说明书中的权威“错误码 → 故障诊断”映射

字段包括手册名称、设备类型、错误码、标题、描述、屏幕/日志原文、报警等级、影响、结构化条件、伴随报警、章节与页码。手册条目支持 JSON 批量导入、LLM 结构化解析、PG + Milvus 同步维护。

相关接口：

- `GET /api/v1/manual-codes`
- `POST /api/v1/manual-codes/parse`
- `POST /api/v1/manual-codes/import-json`
- `POST /api/v1/manual-codes`
- `PUT /api/v1/manual-codes/{id}`
- `DELETE /api/v1/manual-codes/{id}`

## 八、后端 API 模块

| Prefix / 路径 | 模块 | 主要能力 |
| --- | --- | --- |
| `/api/v1/auth` | 认证 | 密码登录、手机验证码、注册、钉钉扫码绑定 |
| `/api/v1/users` | 用户 | 用户 CRUD、当前用户、钉钉解绑 |
| `/api/v1/devices` | 设备 | 设备 CRUD、监控统计、外部状态同步 |
| `/api/v1/work-orders` | 工单 | 工单 CRUD、AI 分析、状态流转、归档、进度日志 |
| `/api/v1/work-order-imports` | 导入 | PDF 上传、抽取批次、人工确认入库 |
| `/api/v1/knowledge` | 知识 | 知识 CRUD、提取、去重、审核 |
| `/api/v1/manual-codes` | 手册 | 错误码 CRUD、解析、JSON 导入 |
| `/api/v1/spare-parts` | 备件 | 备件 CRUD、库存预警、进货导入 |
| `/api/v1/categories` | 分类 | 分类树管理 |
| `/api/v1/fault-codes` | 故障码 | 故障码映射列表与创建 |
| `/api/v1/categories/data/fault-phenomena` | 级联 | 故障现象选项 |
| `/api/v1/categories/data/root-causes` | 级联 | 根本原因选项 |
| `/api/v1/search` | 搜索 | 快速/混合/Agent/问答/追踪维修 |
| `/api/v1/session` | 会话 | 会话摘要压缩 |
| `/api/v1/dashboard` | 驾驶舱 | 聚合统计 |
| `/api/v1/duty-schedules` | 排班 | 排班、复制上周、请假批量登记 |
| `/api/v1/leave-requests` | 请假 | 请假申请、审批、冲突预检 |
| `/api/v1/notifications` | 通知 | 未读数、已读、全部已读 |
| `/api/v1/dispatch` | 派工 | 维修员列表、派工确认 |
| `/api/v1/dingtalk` | 钉钉 | 登录、通讯录、机器人、OA、卡片、移动端工单 |
| `/api/v1/upload` | 上传 | 工单图片/视频上传 |
| `/mcp` | MCP | Streamable HTTP MCP 服务 |

## 九、MCP 工具

MCP 服务通过 `app/mcp/server.py` 挂载到 `/mcp`，与钉钉机器人共用 `app/mcp/tools.py` 的业务实现：

- `search_knowledge`：故障描述检索历史案例并生成分析回答
- `guided_repair_chat`：按钉钉用户维护多轮追踪维修会话
- `query_work_order`：按工单号查询工单详情
- `query_my_workorders`：查询指定用户待处理工单
- `query_inventory`：自然语言库存查询
- `get_user_by_staff`：按钉钉 userId 查询绑定用户
- `get_device_list`：设备列表查询
- `get_knowledge_stats`：知识库统计
- `get_workorder_stats`：工单统计

MCP 访问控制：配置 `MCP_API_KEY` 后要求 `Authorization: Bearer <key>`；未配置时仅允许本机访问。

## 十、主要数据模型

| 模型 | 表 | 用途 |
| --- | --- | --- |
| User | users | 用户、角色、技能、钉钉绑定、负载 |
| Device | devices | 设备台账、运行状态、故障标签、外部系统同步 |
| WorkOrder | work_orders | 工单主数据、故障、处理方案、AI 分析、派工 |
| WorkOrderProgressLog | work_order_progress_logs | 工单状态流转留痕 |
| KnowledgeItem | knowledge_items | 知识库条目、状态、版本、提取元数据 |
| ManualCodeEntry | manual_code_entries | 设备手册错误码权威映射 |
| FaultCodeMapping | fault_code_mappings | 故障码映射 |
| Category | categories | 故障/现象/原因等分类树 |
| SparePart | spare_parts | 备件库存 |
| DutySchedule | duty_schedules | 排班与请假排班 |
| LeaveRequest / Detail | leave_requests / leave_requests_details | 请假申请与按天明细 |
| Notification | notifications | 站内通知 |
| SysConfig | sys_configs | 系统配置 |
| WorkOrderImportBatch / Item | work_order_import_batches / items | 历史工单导入批次与待确认条目 |

## 十一、配置说明

主要配置文件：

- `backend/.env`：后端业务配置，默认模板为 `backend/.env.example`
- 根目录 `.env`：Docker Compose 与 RAGFlow 插值变量

需要关注的关键配置：

| 配置项 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | AI 问答、知识抽取、Agent 的必填密钥 |
| `EMBEDDING_SERVER_URL` | 推理服务地址，默认 `http://localhost:8010` |
| `EMBEDDING_MODEL_NAME` | 召回模型，默认 bge-m3 |
| `RERANKER_MODEL_NAME` | 精排模型，默认 Qwen3-Reranker-0.6B |
| `RERANKER_ENABLED` | 模型精排总开关 |
| `RECALL_TOP_K` / `FINAL_TOP_N` | 召回候选数 / 最终送 LLM 条数 |
| `TRACING_BACKEND` | `ragflow` / `langfuse` / `local` |
| `DINGTALK_*` | 钉钉登录、机器人、OA 审批配置 |
| `SMS_*` | 阿里云短信配置，`SMS_ENABLED=false` 时不发送真实短信 |
| `MCP_API_KEY` | MCP 认证密钥 |

> Redis 端口提醒：`backend/.env` 当前使用 `7379`，但 `docker-compose.dev.yml` 默认插值 `REDIS_PORT=6379`。如果根目录 `.env` 或重建容器后映射端口变化，需要同步修改 `backend/.env` 的 `REDIS_PORT`。

## 十二、脚本与测试

`backend/scripts/` 包含：

- `seed_knowledge.py`：知识种子数据（200 条）
- `seed_categories.py` / `seed_fault_codes.py` / `seed_data.py`：分类、故障码、基础数据
- `import_manual_codes.py`：手册错误码 JSON 导入
- `sync_vectors.py`：知识条目同步到 Milvus
- `calibrate_thresholds.py`：检索阈值校准
- `_download_models.py`：本地模型下载辅助

运行测试：

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests -q
```

现有测试覆盖错误码抽取白名单规则，包括日志时间戳/数值/序列号零误抠、混合码自由匹配、纯数字码白名单过滤。

## 十三、常见问题

| 现象 | 处理 |
| --- | --- |
| 推理服务未就绪 | 启动 `.\start_embedding_server.ps1` 并等待 `/health` 返回 `status=ok` |
| 检索只有 BM25 结果 | 检查推理服务 8010 是否启动，期间系统会自动降级 |
| 端口绑定 `WinError 10013` | 管理员运行 `.\fix_winnat_ports.ps1`，或直接运行 `.\start_all.ps1` |
| 后端连不上 Redis | 核对 `backend/.env` 的 `REDIS_PORT` 与容器实际映射端口 |
| Milvus 连接失败 | 先执行 `docker compose -f docker-compose.dev.yml ps`，确认 etcd/minio/milvus 健康 |
| 新增知识检索不到 | 启动推理服务后执行 `python scripts\sync_vectors.py` |
| 数据库表结构不一致 | 在 `backend` 下执行 `alembic upgrade head` |
| 钉钉回调失效 | 检查 `DINGTALK_REDIRECT_URI`、`SERVER_PUBLIC_URL` 与钉钉后台回调地址 |

## 十四、项目文档

- [项目操作指南](<项目说明/项目操作指南.md>)：初始化、启动、Docker、Git、常见问题
- [检索全链路详解](<项目说明/检索全链路详解.md>)：RAG 链路、RRF、ReAct、调优路线
- [Smart-Repair-System 面试学习指南](<项目说明/Smart-Repair-System 面试学习指南.md>)：架构原理与面试问答
