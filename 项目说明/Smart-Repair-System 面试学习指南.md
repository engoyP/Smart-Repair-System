# Smart-Repair-System 智能维修系统 · 面试学习指南

> 本文档面向求职面试准备，覆盖项目架构、技术选型理由、核心模块原理、踩坑经验与高频面试问答。
> 项目根目录：`d:\Smart-Repair-System`

---

## 目录

1. [项目一页纸概览](#1-项目一页纸概览)
2. [技术栈选型与为什么这么选](#2-技术栈选型与为什么这么选)
3. [整体架构图](#3-整体架构图)
4. [核心模块详解](#4-核心模块详解)
5. [数据模型与存储设计](#5-数据模型与存储设计)
6. [部署与运维](#6-部署与运维)
7. [项目进行中遇到的问题与解决方案](#7-项目进行中遇到的问题与解决方案)
8. [高频面试 Q&A](#8-高频面试-qa)
9. [项目亮点与可吹嘘的点](#9-项目亮点与可吹嘘的点)
10. [面试演示话术](#10-面试演示话术)

---

## 1. 项目一页纸概览

### 1.1 项目定位

**面向制造企业的智能维修知识沉淀与诊断平台**。核心目标：把老师傅的维修经验沉淀成结构化工单和知识库，让新人在遇到设备故障时能通过自然语言提问，AI 检索历史案例并给出诊断建议。

### 1.2 核心能力（一句话总结）

| 能力 | 技术实现 |
|------|----------|
| 工单全生命周期管理 | FastAPI + PostgreSQL + Alembic |
| 维修知识库 RAG 检索 | 双库多路（知识向量/BM25 + 手册精确/手册向量）+ RRF 融合 + 两级模型精排（bge-m3 召回 / Qwen3-Reranker-0.6B 重排）+ 错误码置顶 |
| AI 分析型问答 | DeepSeek LLM + 流式 SSE + 五段式结构化回答 + 验证 Agent 三层把关 |
| 工单智能理解 | LLM 标准化/分类/校验三步走 + 提交时 AI 回填缺失字段 |
| 引导式追踪维修 | LangGraph 对话状态机 + Redis 会话 |
| 钉钉企业集成 | OAuth + Stream 长连接 + 机器人 LangGraph 路由 |
| 专家模式 | 多故障拆解（规则预检 + LLM）+ 并行 ReAct 检索 + 分组流式回答 |
| 工单→知识沉淀闭环 | 完成工单自动抽取 → 三层去重 → 发布 → 同步 Milvus（数据飞轮） |
| MCP 集成 | fastmcp 将检索/工单/库存能力暴露为标准 MCP 工具（Streamable HTTP） |

### 1.3 业务价值

1. **(1)** 维修响应时间从"问老师傅"的几十分钟缩短到 AI 检索的几秒
2. **(2)** 隐性经验显性化：老师傅离职不带走知识
3. **(3)** 复合故障（锁模力+油温+马达同时出问题）能拆解成多个单故障并行诊断，避免单检索语义稀释
4. **(4)** 工单质量把关：提交完成时 AI 标准化分析并回填缺失字段，主管/管理员最终审核把关，保证入库知识质量

---

## 2. 技术栈选型与为什么这么选

### 2.1 后端栈

| 技术 | 版本 | 选型理由 |
|------|------|----------|
| **FastAPI** | 0.135.3 | 原生 async + Pydantic 校验 + OpenAPI 自动文档，适合 AI 接口的流式 SSE |
| **SQLAlchemy** | 2.0.25 | ORM，Type 注解更现代；项目主要用同步 Session（FastAPI 路由层 async + 阻塞调用 ORM） |
| **Pydantic** | 2.12.5 | v2 性能比 v1 快 5-10 倍；所有 API 请求/响应严格类型化 |
| **Alembic** | 1.13.1 | 数据库迁移版本控制 |
| **loguru** | 0.7.2 | 比 stdlib logging 配置简单，原生支持 rotation/retention |

### 2.2 AI / LLM 栈

| 技术 | 用途 | 选型理由 |
|------|------|----------|
| **LangChain** | 1.3.13 | LLM 调用统一封装，Prompt 模板，Message 抽象 |
| **langchain-openai** | 1.2.2 | OpenAI 兼容适配层，DeepSeek API 走这个通道 |
| **langchain-community** | 0.4.2 | 社区集成（工具、向量库适配等） |
| **LangGraph** | 1.2.6 | StateGraph 状态机，适合钉钉意图路由和引导式维修的多步对话 |
| **DeepSeek** | deepseek-chat | 国产 LLM，性价比高，中文维修场景效果好 |
| **bge-m3**（召回） | 本地 Embedding | BAAI 出品，1024 维，多语言/长文本（8192），**独立推理服务化**（8010，OpenAI 兼容）；仅取 dense 向量（已 L2 归一化） |
| **Qwen3-Reranker-0.6B**（精排） | 本地 Reranker | cross-encoder：问题×候选联合编码打分，精排阶段替代规则重排，BEIR ~71% |

### 2.3 数据存储栈

| 技术 | 用途 | 选型理由 |
|------|------|----------|
| **PostgreSQL** | 16 | 业务数据 + BM25 全文检索（ILIKE 加权评分）+ 会话持久化 |
| **Milvus** | 2.4.15 | 向量数据库，**IVF_FLAT + COSINE** 索引，1024 维 |
| **Redis** | 7 | 会话缓存（24h TTL）+ 复用检索结果 |
| **MinIO** | - | Milvus 的对象存储后端 |
| **etcd** | - | Milvus 的元数据存储 |

### 2.4 前端栈

| 技术 | 用途 |
|------|------|
| **Vue 3** | 渐进式框架，Composition API |
| **Vite** | 构建工具，HMR 快 |
| **Pinia** | 状态管理（比 Vuex 简洁） |
| **Element Plus** | UI 组件库 |

### 2.5 集成与部署

| 技术 | 用途 |
|------|------|
| **Docker Compose** | 一键拉起 PG/Redis/Milvus/MinIO/etcd |
| **钉钉开放平台** | OAuth 登录 + 机器人单聊 + OA 审批同步 |
| **APScheduler** | 后台定时任务（OA 审批同步） |
| **cpolar** | 内网穿透，用于钉钉 OAuth 回调 |

---

## 3. 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端 Vue3 + Vite                         │
│   维修报表 / 知识库 / AI问答 / 数据驾驶舱 / 备件库存 / 排班       │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / SSE
┌────────────────────────────▼────────────────────────────────────┐
│                    FastAPI 后端 (app/main.py)                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  路由层 (21 个 prefix)                                    │   │
│  │  /work-orders /knowledge /search /session /dingtalk ...  │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Agent 层（核心智能）                                      │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐   │   │
│  │  │ QA_GRAPH    │  │ AnswerAgent  │  │ GuidedRepair   │   │   │
│  │  │ 主图+3子图   │  │ (流式五段式)  │  │ Agent(LangGraph)│   │   │
│  │  │ (故障子图接  │  │              │  │ 对话状态机      │   │   │
│  │  │  验证Agent) │  │              │  │                │   │   │
│  │  └─────────────┘  └──────────────┘  └────────────────┘   │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐   │   │
│  │  │ TicketAgent │  │ RobotGraph   │  │ FaultDecomposer│   │   │
│  │  │ (工单理解)   │  │ (钉钉路由)    │  │ (专家模式拆解)  │   │   │
│  │  └─────────────┘  └──────────────┘  └────────────────┘   │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐   │   │
│  │  │ VerifyAgent │  │ DedupAgent   │  │ RetrievalAsst  │   │   │
│  │  │ (三层把关)   │  │ (知识判重)    │  │ Agent(ReAct循环)│   │   │
│  │  └─────────────┘  └──────────────┘  └────────────────┘   │   │
│  │  ┌──────────────────────────────────────────────────────┐ │   │
│  │  │  KnowledgeExtractorAgent（工单→知识抽取，数据飞轮）       │ │   │
│  │  └──────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  检索编排层 RetrievalFlow（问答/专家/钉钉/MCP 共用）        │   │
│  │  retrieve_hybrid：查询理解→双库多路召回→RRF融合            │   │
│  │  filter_rerank_cases：过滤→模型精排→严格过滤→错误码置顶    │   │
│  │  extract_error_codes：纯正则识别错误码→决定 2 路/4 路      │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  工具层 RetrievalTools + QueryExtractor                  │   │
│  │  vector_search / bm25_search / manual_code_search        │   │
│  │  manual_vector_search / rrf_merge / weighted_rerank      │   │
│  │  query_extractor（白名单+LLM兜底）/ clean_query           │   │
│  └──────────────────────────────────────────────────────────┘   │
└─┬───────────────┬───────────────┬───────────────┬───────────────┘
  │               │               │               │
┌─▼─────────┐ ┌───▼─────┐  ┌──────▼─────┐   ┌─────▼─────┐
│ PostgreSQL│ │  Redis  │  │   Milvus   │   │ DeepSeek  │
│ 业务数据   │ │ 会话缓存 │  │  双集合     │   │   LLM     │
│ knowledge │ │ 24h TTL │  │ knowledge  │   │           │
│ manual_   │ │         │  │ log_code   │   │           │
│ code_     │ │         │  │ IVF_FLAT   │   │           │
│ entries   │ │         │  │ + COSINE   │   │           │
│ (pg_trgm  │ │         │  │ nlist=1024 │   │           │
│  GIN 索引) │ │         │  │ nprobe=16  │   │           │
└───────────┘ └─────────┘  └──────┬─────┘   └───────────┘
                                  │
                            ┌─────▼─────┐
                            │  MinIO    │  ← Milvus 对象存储
                            │  etcd     │  ← Milvus 元数据
                            └───────────┘

┌─────────────────────────────────────────────────────────────────┐
│              外部集成：钉钉开放平台                                │
│  OAuth 回调 / Stream 长连接 / 机器人消息 / OA 审批同步             │
├─────────────────────────────────────────────────────────────────┤
│              MCP Server（/mcp，Streamable HTTP）                  │
│  search_knowledge / guided_repair_chat / query_work_order ...     │
│  （fastmcp，API Key 或本机 IP 认证；检索走同一套 RetrievalFlow）   │
└─────────────────────────────────────────────────────────────────┘
```

**检索链路在架构中的位置（与 4.1 对应）**：
- **入口复用**：智能问答（QA_GRAPH）、专家模式（FaultDecomposer → 并行 ReAct）、钉钉机器人（RobotGraph）、MCP 工具——四者都走 `retrieval_flow.py` 这一套检索编排（召回 → 融合 → 过滤重排），差异只在 Agent 分工
- **双库四路召回**：知识库（Milvus 向量 + PG BM25）总是走；问题含错误码时增开手册库（PG 精确 `manual_code_entries` + Milvus 向量 `log_code`），最多四路（见 4.1.5）
- **双路索引对称**：Milvus 双集合共用 IVF_FLAT + COSINE（nlist=1024/nprobe=16，见 4.1.8）；PG 的 `knowledge_items.title/content` 建 pg_trgm GIN 索引加速 BM25 的 `ILIKE %词%`（见 4.1.6）

---

## 4. 核心模块详解

### 4.1 知识检索（RAG 核心）— `app/api/search.py` + `app/agents/tools.py`

#### 4.1.1 检索流程（五步走）

```
用户 query
    │
    ▼
[Step 1] 查询清洗 (clean_query_for_retrieval)
    │   - 去标点 → 保护固定故障词（跳闸/报警）→ 拆中文span/英文span
    │   - 前缀剥离 → 后缀剥离 → 中间高置信词替换
    │   - 单字中文丢弃 → 还原固定词
    ▼
[Step 2] 关键词提取 (QueryKeywordExtractor)
    │   - 白名单匹配（设备类型词 + 故障信号词）
    │   - LLM 兜底（白名单未命中时调用 LLM 提取技术词）
    ▼
[Step 3] 并行混合检索
    │   ├── 向量检索：Milvus IVF_FLAT + COSINE，score_threshold=0.0
    │   └── BM25 检索：PostgreSQL ILIKE 加权评分
    │       - 故障原因词权重 5（标题）/ 2（内容）
    │       - 设备类型词权重 1（标题）/ 1（内容）
    │       - SQL: WHERE (title ILIKE :kw OR content ILIKE :kw) OR ...
    ▼
[Step 4] RRF 融合 (rrf_merge)
    │   - k=60 平滑参数
    │   - 按 knowledge_id 跨路去重（关键！避免同条工单双路命中分不合并）
    │   - 显示分数用向量余弦相似度，BM25 独中显示 0%
    │   - ⚠️ 手册库加入后为"双库最多四路融合"（知识向量/BM25 + 手册精确/手册向量），见 4.1.5
    ▼
[Step 5] 模型精排 (Qwen3-Reranker-0.6B)
    │   - 召回扩到 top 30（RECALL_TOP_K），RRF 融合后取前 30 条候选
    │   - reranker 对"问题 × 每条候选"联合编码打分（cross-encoder）
    │   - 模型分存 rerank_score 独立字段：只排序、不过滤（过滤仍按向量分数）
    │   - 推理服务不可用 → 自动降级规则重排 weighted_rerank
    │     （设备不匹配 → ×0.2 / 命中率<0.3 → ×0.15 / ≥0.3 → ×(1+0.4×ratio)）
    ▼
最终 top_k 案例（FINAL_TOP_N=10）
   - 通用过滤：score ≥ 0.15（丢弃低相关案例）
   - 问答 / 专家模式额外叠加"设备 + 故障关键词严格过滤"（见 4.1.4）
```

#### 4.1.2 为什么这么设计

1. **(1) 向量 + BM25 双路**：向量擅长语义近似（"嗡嗡响" ≈ "异响"），BM25 擅长关键词精确匹配（故障码、设备型号）。单路都有盲区，RRF 融合能取长补短。
2. **(2) RRF 而非简单加权**：RRF 只用排名（rank）不用原始分数，避免向量余弦分数和 BM25 分数量纲不同导致融合失真。`k=60` 是工业界经验值。
3. **(3) 按 knowledge_id 去重**：向量路返回的 `id` 是 Milvus 的 UUID point_id，BM25 路返回的 `id` 是 PG 主键整数。如果用 `id` 做合并键，同一条工单双路命中无法合并分数。**这是一个真实踩过的坑**。
4. **(4) 查询清洗**：用户提问里"怎么回事/可能/我你觉得"这些干扰词会严重污染语义向量。清洗后向量更"纯"，召回率显著提升。
5. **(5) 模型精排 + 规则兜底**：精排用 Qwen3-Reranker（cross-encoder，问题×案例联合编码）——它同时"看到"问题和候选全文，比 bi-encoder 向量相似度更能捕捉"设备+故障"的细粒度匹配（"注塑机温度高"匹配到"锅炉温度高"这种跨设备相似会被压低）；规则 `weighted_rerank`（设备不匹配 ×0.2 惩罚）保留为**降级路径**，推理服务不可用时自动顶上。

#### 4.1.3 关键接口

```python
# app/agents/tools.py
class RetrievalTools:
    def vector_search(query, top_k, device_type, fault_code, score_threshold) -> ToolResult
    def bm25_search(query, top_k, device_type, fault_code) -> ToolResult
    def conditional_query(device_type, fault_code, tags, keyword, top_k) -> ToolResult
    def rewrite_query(original_query, context, strategy) -> ToolResult
    def graph_query(device_type, fault_code, exclude_ids, top_k) -> ToolResult

# 模块级函数
def rrf_merge(result_sets, k=60, top_n=10) -> List[Dict]
def weighted_rerank(results, query, fault_weight, device_penalty, cleaned_query) -> List[Dict]
def clean_query_for_retrieval(query) -> str
```

**这些接口分两类，角色完全不同**：

**① `RetrievalTools` 方法 = ReAct Agent 的"行动空间"**（对应 `retrieval_agent.py` 的 `AgentAction` 枚举，每轮 LLM 从这些动作里选一个执行）：

| 接口 | 做什么 | 底层 | 适合场景 |
|---|---|---|---|
| `vector_search` | 向量语义检索：QueryExtractor 清洗 → 编码 → Milvus `knowledge` 集合（IVF_FLAT+COSINE） | Milvus + Embedding | 模糊/口语化描述，按意思匹配 |
| `bm25_search` | 关键词加权检索：2/3-gram 切词 → PG `ILIKE` + 故障词 5/2 加权 | PostgreSQL | 含明确关键词/故障码/设备编号 |
| `conditional_query` | 结构化字段精确筛选（device_type/fault_code/tags/keyword），纯 SQL 零 LLM | PostgreSQL | 已确定设备类型/故障码/标签，按字段精确捞 |
| `graph_query` | 关联查询：以设备/故障为起点展开相关条目，`exclude_ids` 自动排除已查到的 | PostgreSQL | 查周边相关知识，补全上下文 |
| `rewrite_query` | 查询改写（不检索）：LLM 改写成专业表述（expand_synonyms/technical_terms/generalize） | DeepSeek LLM | 结果不足时的重试路径，改写后下一轮重新检索 |

> 注意：`graph_query` 名字带 "graph" 但**不是图数据库**，是知识关联查询（按字段展开 + 排除已见），没有真正的图遍历。

**② 模块级函数 = 检索流水线的算法步骤**（不是给 LLM 用的，代码确定性调用）：

| 接口 | 做什么 | 在链路哪一步 |
|---|---|---|
| `rrf_merge` | RRF 名次融合：`Σ 1/(k+rank)`，k=60，`_dedup_key` > `knowledge_id` > `id` 去重 | 多路召回之后合并排序（见 4.1.5） |
| `weighted_rerank` | 规则加权重排（**降级路径**）：设备不匹配 ×0.2 / 命中率<0.3→×0.15 / ≥0.3→×(1+0.4×ratio) | 模型精排（Qwen3-Reranker）不可用时的兜底（见 4.1.1 Step 5 / 4.7） |
| `clean_query_for_retrieval` | 查询清洗：去标点→保护故障词→中文 span 前后缀剥离+中间疑问词替换→还原 | 检索最前置（向量编码/BM25 切词前都过它） |

**一句话总结关系**：

```
用户问题
  → clean_query_for_retrieval（清洗，纯函数）
  → vector_search + bm25_search（召回，固定双路）
  → (含错误码) manual_code_search + manual_vector_search（手册双路）
  → rrf_merge（融合，纯函数）
  → Qwen3-Reranker 模型精排（降级：weighted_rerank）→ filter_rerank_cases（精排，纯函数）
  → 喂 LLM

搜索页/专家模式（ReAct）额外：
  → 每轮 LLM 从 6 个动作里选（vector/bm25/conditional/graph/rewrite/finish）
  → rewrite_query 改写 → 下一轮重新走召回
```

> 本质区别：`RetrievalTools` 的 5 个方法是"**工具**"（供 Agent 决策调用，动态）；3 个模块级函数是"**算法**"（供流水线确定性执行，静态）。

#### 4.1.4 三种检索入口的策略差异

| 入口 | 端点 | 策略 | 特点 |
|---|---|---|---|
| 知识搜索页 | `/agent` | ReAct Agent：LLM 决策选 vector/bm25/conditional/graph，最多 5 轮 | 质量优先，慢，只查不答 |
| 智能问答 | `/answer/stream` | 固定混合检索（vector+BM25 → RRF → 模型精排 → 严格过滤）→ LLM 五段式回答 | 快、稳；多故障提问会提示切专家模式 |
| 专家模式 | `/answer/expert` | 多故障拆解（规则预检 + LLM）→ 各故障并行 ReAct（首轮强制双路）→ 分组回答 | 复杂 / 复合问题深度分析 |

> 鉴权差异：`/agent`（搜索页）无需登录；`/answer/stream`、`/answer/expert` 与 `/guided-repair/*` 均需 `Authorization: Bearer <token>`（登录后获取）。

**强制混合检索（`require_hybrid`）**：专家模式首轮不走 LLM 决策，确定性执行 vector + BM25 双路，质量达标直接进 RRF 融合；不达标才进入 LLM 决策循环。解决"ReAct 第一轮选 vector 且达标就早停，混合检索名存实亡"的问题。

**严格过滤（`_filter_rerank_cases`）**：问答 / 专家模式在通用 0.15 阈值之上，再按"设备类型精确匹配 + 故障关键词至少命中一个"过滤，剔除跨设备案例（如"数控机床主轴过热"误召回"输送设备电机过热"）和同设备泛相似案例（如"黑屏"）；严格过滤为空时回退宽松 top2，避免误伤导致"未检索到"。

#### 4.1.5 双库四路融合与错误码路由（手册库加入后）

> 公共编排层：`app/agents/retrieval_flow.py`（智能问答/专家/钉钉/验证 Agent 共用；/quick、/hybrid、/manual-lookup、ReAct、追踪维修各自内联）

**不是 4 个库，是 2 个库最多 4 路检索**：

```
                    ┌─ 知识库（knowledge） ① 向量检索（cos，Milvus）
                    │                      ② BM25 关键词检索
   问题 ── 提取错误码 ┤
  （含错误码才走③④）│ 手册库（log_code）  ③ 错误码精确匹配（查 PG 表，非向量）
                    │                      ④ 手册语义向量（Milvus）
                    └─ 全部路 → rrf_merge（按名次）→ 严格过滤 → 错误码置顶
```

| 路 | 检索方式 | 数据源 | 触发条件 |
|---|---|---|---|
| ① | 向量（cos） | 知识库 Milvus | 总是 |
| ② | BM25（关键词） | 知识库 | 总是 |
| ③ | 错误码精确匹配 | 手册库 PG 表 | 仅问题含错误码 |
| ④ | 手册语义向量 | 手册库 Milvus | 仅问题含错误码 |

**① 走 2 路还是 4 路的判断**（`extract_error_codes`，纯正则零 LLM）：提取到错误码 → 4 路；否则 2 路。提取规则两条：
- **字母 + 数字混合 token**：`SV0436` / `ALM-6401` / `E3091` → 去分隔符 + 大写归一化（`ALM-6401`→`ALM6401`），长度 ≥ 3 且非纯数字
- **纯数字 4~6 位**：`6401` / `0401` 视为报警码，但**排除年份**（恰好 4 位且 `19`/`20` 开头不算）
- 设计取舍：**误判无害**（最多多查一路手册，结果里没有手册条目不影响回答），**漏判是已知边界**（非规范格式错误码提取不到 → 走 2 路，不启用手册权威答案）；用正则而非 LLM 是因为零成本、可预测、无幻觉，语义理解交给后面的向量路和验证 Agent（职责分层）

**② 为什么 RRF 而不是直接比 cos 分数**：① 的向量 cos、② 的 BM25 得分、③ 的精确匹配——三者**分数量纲完全不同**，直接加不科学；RRF 只用名次（`1/(k+rank)`，k=60）跨路求和，天然规避跨源分数归一化。

**③ 融合去重 key 的层级**：`_dedup_key`（复合键，仅手册条目带 `M:{id}`，知识条目不带）> `knowledge_id` > `id`。三个真实坑：
- 知识库和手册库主键都是 PG 自增 int，纯按 id 去重会**撞号**（知识 id=5 和手册 id=5 被当同一实体合并丢条目）→ 用复合 key 隔离来源
- 向量路 id 是 Milvus UUID、BM25 路 id 是 PG int，按 id 合并会把"同一条双路命中"拆成两条 → 双路 RRF 分加不上

**④ 错误码精确匹配名次吃亏 → 置顶修正**：③ 最权威（score=1.0），但 RRF 按名次算只在一路出现，会被知识库泛案例挤下去 → 融合过滤后按 `method == manual_code_exact` **置顶**，否则"SV0436 精确命中"排不过泛相似案例。

#### 4.1.6 BM25 性能优化：pg_trgm 索引（已实施）

> 目标：让 `ILIKE '%关键词%'` 模糊匹配在上千条知识后依然毫秒级，避免退化为全表扫描。

**为什么做（问题背景）**

- BM25 的 SQL 是 `title ILIKE '%词%' OR content ILIKE '%词%'`——`%词%` 意味着"任意位置包含"，位置不确定
- 没有索引时，PostgreSQL 只能**逐行全文扫描**（复杂度 O(n)）：几百条时毫秒级无感，到**上万条会明显变慢**
- 向量路靠 Milvus ANN 索引天然可扩展，**BM25 是全链路唯一随数据量恶化的环节**，必须提前铺路

**为什么普通索引不行**

- 数据库默认的 B-tree 索引只擅长"精确值 / 前缀"匹配（`title = 'xx'` 或 `LIKE 'xx%'`），对中间的 `%xx%` 无能为力
- 需要专门为"子串包含匹配"设计的工具：**pg_trgm**

**怎么实现（原理）**

1. **建索引时**（一次性）：把每段文本切成**连续的 3 字片段（trigram）**

   ```
   "注塑机温度过高" → 注塑机, 塑机温, 机温度, 温度过, 度过高
   ```

2. 用 **GIN 倒排索引**登记：每个 trigram → 包含它的所有行号

   ```
   "注塑机" → {第5行, 第89行, ...}
   ```

3. **查询时**：查询词切 trigram → 查倒排索引直接拿到候选行号（哈希定位，O(1)）→ 只对候选行做精确 ILIKE 验证（防假命中）

   ```
   10000 行全扫  →  索引锁定几十行候选  →  只验证这几行
   ```

**益处**

- 查询复杂度从 **O(n)（全表扫描）降到 O(候选集)**，数据越多差距越大
- 写入代价极小（每次插入只登记几个 trigram，毫秒级）；知识库"读多写少"，非常划算
- 与向量路的 Milvus ANN 索引形成对称：**两条检索路都有索引支撑，数据增长不拖累任何一路**

**实现细节（已落地）**

- Alembic migration `7a8b9c0d1e2f`（`backend/alembic/versions/7a8b9c0d1e2f_add_pg_trgm_indexes.py`，可回滚，downgrade 只删索引保留 extension）：

  ```sql
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE INDEX idx_knowledge_title_trgm ON knowledge_items USING gin (title gin_trgm_ops);
  CREATE INDEX idx_knowledge_content_trgm ON knowledge_items USING gin (content gin_trgm_ops);
  ```

- 已验证：强制走索引时执行计划显示 `Bitmap Index Scan on idx_knowledge_title_trgm / idx_knowledge_content_trgm`

**边界与注意**

- **查询词 ≥3 字提速最明显**（有 trigram 可拆）；2 字词（如"温度"）没有 trigram，会部分退化——BM25 的 2-gram/3-gram 混合切词恰好长短互补
- **数据量小时优化器自动选全表扫描**——全扫比索引便宜，这是正常的（当时约 25 条时就是全扫）；数据量上千后优化器会**自动**改用 Bitmap Index Scan，无需改动代码

#### 4.1.7 BM25 检索调优策略

> BM25 路的完整调优：召回策略（切词/加权/OR）→ 索引支撑（pg_trgm）→ 规模增长后的演进方向。

**① 加权评分：故障词是核心信号，设备词是定位上下文**（`bm25_search`，已实现）

| 词类别 | 命中标题 | 命中内容 | 设计意图 |
|---|---|---|---|
| 故障原因词 | **5** | **2** | 故障描述是相关性最核心的信号；标题比正文凝练更可信 |
| 设备类型词 | 1 | 1 | 设备只是定位上下文，权重刻意压低 |

- 一句话：**"描述什么故障"比"发生在什么设备上"更能决定相关度**——"电机异响"搜出"电机异响排查"排在"电机保养"前面
- SQL 实现：`CASE WHEN title ILIKE :kw THEN w1 ELSE 0 END + CASE WHEN content ILIKE :kw THEN w2 ELSE 0 END` 累加计分

**② 中文切词：2-gram/3-gram 重叠切分（无 jieba）**

```
"注塑机温度过高" → {注塑机, 注塑, 塑机, 温度, 过高}
```

- 中文无空格，不能按空格分词；引入 jieba 增加依赖和延迟，用 n-gram 重叠切分近似覆盖复合词变体
- **2/3-gram 长短互补**：3-gram 有 trigram 可走 pg_trgm 索引（≥3 字提速最明显）；2-gram 兜底 2 字词（"温度"），虽部分退化但不漏
- 英文/数字 token 按空格分词（`PLC`、`6101` 直接参与匹配）

**③ 召回策略：OR 连接宁多勿漏**

```sql
WHERE (title ILIKE '%温度%' OR content ILIKE '%温度%')
   OR (title ILIKE '%过高%' OR content ILIKE '%过高%') ...
```

- 任一关键词命中即召回，允许噪音——召回阶段的任务是"别漏"，由后段 RRF 融合 + 过滤 + 重排清理噪音（见 4.1.1 Step 4/5）
- 排序靠加权分数，不是靠命中个数（长文本不会靠重复词刷分）

**④ 索引支撑：pg_trgm**（已实施，见 4.1.6）

`%词%` 任意位置匹配 B-tree 无能为力，必须 pg_trgm GIN 索引；复杂度从 O(n) 全表扫降到 O(候选集)，与向量路 Milvus ANN 索引对称。

**⑤ 规模增长后的演进方向**（前瞻，当前数据量小未落地）：

| 演进 | 要解决的问题 | 做法 |
|---|---|---|
| 确认索引生效 | 数据量上千后 ILIKE 退化 | `EXPLAIN` 确认走 `Bitmap Index Scan on idx_*_trgm` |
| 按需分区 | 全表扫描范围仍大 | 按设备类型 / 时间分区 |
| 动态阈值 | 固定 0.15 无法区分"没查到"和"查到不相关" | 精确查询（含故障码）阈值 0.30；模糊查询用动态百分位 |
| 两阶段检索 | top-8 可能漏掉正确案例 | 粗排召回扩到 top 50~100 → 精排选 8 |
| 缓存层 | 高频问题重复消耗 Milvus/LLM | `question + device_type` → Redis 缓存，知识库版本变更失效 |

**面试可背的一句话**：
> "BM25 路的调优分三层——召回层用 2/3-gram 切词 + 故障词 5/2 加权（故障是核心信号、设备是定位上下文）+ OR 宁多勿漏；索引层用 pg_trgm GIN 解决 `%词%` 全表扫描，与 Milvus ANN 索引对称；规模增长后走分区 + 动态阈值 + 两阶段检索。"

#### 4.1.8 向量索引检索详解：Milvus IVF_FLAT + COSINE

> 与 4.1.7（BM25 调优）对称：BM25 路靠 PG pg_trgm 索引，向量路靠 Milvus ANN 索引——两条检索路都有索引支撑，数据增长不拖累任何一路。
> 代码：`backend/app/core/vector_store.py#L136-L150`（基类 `_create_index`，两个集合共用同一套索引）。

**① 为什么需要索引（问题背景）**

向量是 1024 维 float 数组，检索 = "找与查询向量最相似的 N 个"。暴力全库算余弦相似度在数据量上来后不可接受，需要**近似最近邻（ANN）索引**：牺牲一点点精度，换取几十上百倍加速。`IVF_FLAT` 是最经典的 ANN 算法之一。

**② IVF_FLAT 原理：倒排文件 + 候选区暴力精排**

```
建库（写入时，一次性）：
  1. KMeans 把所有向量聚成 nlist 个簇（中心点）
  2. 每个向量分到距离最近的簇 → 建立"簇 → 向量列表"倒排索引

查询（每次检索）：
  1. 算查询向量与 nlist 个簇中心的距离
  2. 只进距离最近的 nprobe 个簇（候选区）
  3. 候选区内暴力算余弦相似度，精排返回 top_k
```

- **FLAT 的含义**：候选区内计算是精确的暴力全算（不压缩向量），不像 `IVF_PQ`/`IVF_SQ8` 会量化损失精度——"索引加速 + 结果无损"的组合
- 本项目：`nlist=1024`，检索 `nprobe=16` → 每次只搜全库 **16/1024 ≈ 1.5%** 的数据，毫秒级响应

**③ 两个关键参数：nlist / nprobe**

| 参数 | 含义 | 本项目取值 | 权衡 |
|---|---|---|---|
| `nlist` | 建库时分多少簇 | 1024 | 越大候选区越细，但建库慢 |
| `nprobe` | 查询时搜几个簇 | 16 | 越大召回越全越慢；越小越快可能漏 |

> 面试点：**nprobe 是精度与延迟的唯一旋钮**——它决定了"近似"的程度，比 nlist 更影响线上检索质量。

**④ 为什么选 COSINE 度量**

```
cos(θ) = (query · 知识) / (|query| × |知识|)
```

- 本项目召回模型 bge-m3 的 dense 输出已 **L2 归一化**，向量长度压成 1 → **余弦相似度 = 点积**，Milvus 计算快、索引友好
- COSINE 只关心方向、不关心长度——语义相似度场景"方向一致 = 语义相近"（"温度过高"和"温度偏高"向量接近）
- 归一化后 COSINE 与 L2 欧氏数学上等价（`|A-B|² = 2 - 2cos(A,B)`），但 COSINE 语义更直观

**⑤ 两个集合共用同一套索引**

| 集合 | 存什么 | 检索入口 | 额外标量过滤 |
|---|---|---|---|
| `knowledge` | 知识条目 | `VectorStore.search`（基类，vector_store.py:211） | `device_type` / `fault_code` 表达式 |
| `log_code` | 手册错误码 | `LogCodeVectorStore.search`（vector_store.py:509） | `device_type` / `error_code` 表达式 |

两个 search 都支持 `expr` 标量过滤表达式（如 `device_type == "注塑机"`），实现"先按条件过滤候选、再向量精排"。

**⑥ 为什么 score_threshold=0.0（全量召回）**

向量路设 0 阈值全量召回，**不把相关性把关放在早期**——交给后面的 RRF 融合 + 加权重排 + 严格过滤统一处理，避免单路阈值误杀。召回层宁多勿漏，精排层再精修。

**面试可背的一句话**：
> "向量路用 Milvus IVF_FLAT + COSINE：建库时 KMeans 聚成 1024 个簇做倒排索引，查询时只进最近的 16 个簇暴力精排，只搜 1.5% 的数据；Embedding 已 L2 归一化所以余弦 = 点积；score_threshold=0.0 全量召回，相关性把关统一放到融合重排阶段。"

---

### 4.2 AI 分析型问答 — `app/agents/answer_agent.py`

#### 4.2.1 五段式回答结构

LLM 根据问题类型选择对应格式：

**故障诊断查询**（如"XX 不亮""XX 报警怎么处理"）：
1. **问题分析**：基于案例定位故障本质
2. **可能原因**：列出案例中明确提到的所有可能原因，按可能性排序
3. **排查方向**：具体排查步骤、测量参数、判断标准
4. **处理方案**：详细维修方法和操作步骤
5. **预防建议**：案例中提到的预防措施，没有则写"未提及"

**设备类型查询**（如"XX 设备有哪些"）：
- 汇总设备类型 + 故障码 + 典型故障表现

#### 4.2.2 关键约束（避免 LLM 瞎编）

System Prompt 里硬约束：
1. **只回答检索到的内容**，不得编造、推测
2. **如实回答无匹配**，不得强行拼凑
3. **分数由系统决定**，不得修改、重打分
4. **不提供通用建议**，不得使用案例之外的维修经验

> 这是项目最关键的约束：**案例来源必须是真实工单，不能是 AI 生成的**。

#### 4.2.3 流式 SSE 实现

```python
# app/api/search.py - /answer/stream
async def stream():
    yield f"data: {json.dumps({'type': 'thinking'})}\n\n"   # 立即响应"思考中"
    if fault_decomposer._looks_compound(question):           # 规则预检多故障（零 LLM）
        yield f"data: {json.dumps({'type': 'suggest_expert'})}\n\n"  # 建议切专家模式
    # ... 检索案例（严格过滤后）...
    yield f"event: references\ndata: {json.dumps(references)}\n\n"  # 推送参考案例
    for chunk in self.llm.stream(messages):  # 流式生成回答
        yield f"data: {json.dumps({'type': 'answer', 'content': chunk.content})}\n\n"
    yield f"data: {json.dumps({'type': 'done', 'confidence': ...})}\n\n"
```

**为什么用 SSE 而不是 WebSocket**：SSE 单向推送够用、HTTP 兼容性好、自动重连、不需要协议升级。

#### 4.2.4 库存查询前置判断

`is_inventory_query()` 用关键词匹配（"库存/备件/还有多少"），命中则走 `SparePart` 表直接查询，不走 LLM。**避免无意义的 LLM 调用**。

#### 4.2.5 多故障检测与串味治理

**多故障检测（提示层）**：`/answer/stream` 检索前用 `fault_decomposer._looks_compound()`（纯规则预检：连接词 + ≥2 个不同故障信号词，零 LLM 调用）判断是否为复合故障提问。命中则推送 `{"type": "suggest_expert"}` 事件，前端在回答完成后显示"检测到提问包含多个故障现象"提示条 + "切换到专家模式"按钮，一键新建专家会话并重新提问。

**串味治理（检索层）**：问答模式检索后调用与专家模式同一套 `_filter_rerank_cases`：
1. 过滤 `rrf_only` / 低分（score < 0.15）
2. **Qwen3-Reranker 模型精排**（降级路径：`weighted_rerank` 规则重排——故障词权重 0.4、设备不匹配 ×0.2 压低）
3. **严格过滤**：设备类型精确匹配 + 案例标题/正文至少命中一个故障关键词
4. 严格过滤为空时回退宽松 top2，防止误伤导致"未检索到"

效果："数控机床主轴过热还有换刀故障"不会再引用黑屏、输送设备电机过热等无关案例。

---

### 4.3 专家模式：多故障拆解 + 并行 ReAct 检索（`/answer/expert`）

> 文件：`app/agents/fault_decomposer.py` + `app/api/search.py`（`expert_answer_stream`）
> 端点：`POST /api/v1/search/answer/expert`（SSE 流式，事件协议与 `/answer/stream` 一致）

#### 4.3.1 为什么需要拆解

**单检索的痛点**：复合故障被语义稀释。例如用户问"3 号注塑机锁模力不够出飞边 + 液压油温 65 度报警 + 熔胶马达不转电机嗡嗡响"，同时含机械、液压、电气三个故障域。单次向量检索的 query 是三个域语义的"平均"，会被稀释，top_k 里三域各混进来几条，分数最高的未必对应用户最关心的故障点。

#### 4.3.2 架构流转

```
用户复合故障问题
    │
    ▼
┌──────── FaultDecomposer（拆解）────────┐
│  Step1 规则预检 _looks_compound        │
│    连接词 + ≥2 个故障信号词（零 LLM）    │
│  Step2 LLM 拆解为单故障子查询            │
│    输出: ["注塑机 锁模力飞边", ...]      │
│    上限 4 个（_MAX_SUB_QUERIES）        │
│    兜底: LLM 失败 → 按原问题整体处理      │
└────────────────┬──────────────────────┘
                 │
    ┌────────────┴────────────┐
    ▼ 单一故障                ▼ 多故障
 走 ReAct 智能检索        并行子查询
                          asyncio.gather + asyncio.to_thread
                          （拆解上限 4，整体超时 90s）
    ┌───────────────────────┴──────────────────┐
    ▼                                           ▼
[单故障 ReAct]                        每个子查询独立 _run_agent_search
                                      = RetrievalAssistantAgent（ReAct 循环）
                                        → 首轮强制 vector+BM25 双路（require_hybrid）
                                        → 质量不达标才进入 LLM 决策循环
    └───────────────────────┬──────────────────┘
                            ▼
        各故障独立严格过滤（filter_rerank_cases + 错误码置顶）
                            ▼
        AnswerAgent.stream_answer_multi 分组流式回答
        （每个故障一个小节，案例带 fault 归属标签）
```

#### 4.3.3 为什么用 ReAct 而非固定检索

单故障场景走 `RetrievalAssistantAgent`（ReAct 循环）：**首轮强制混合检索**（`require_hybrid`，确定性执行 vector + BM25 双路）→ 判断结果质量 → 不达标才进入 LLM 决策循环（改写查询 / 换检索路 / 加条件查询），最多 5 轮。解决"固定混合检索第一轮达标就早停，混合检索名存实亡"的盲区。

#### 4.3.4 多故障分组流式

- 每个子查询独立检索、独立过滤，参考案例带 `fault` 字段标明归属故障
- 跨故障参考案例全局按匹配度降序，故障标签保留（前端可分组展示）
- 回答按故障分组流式输出（`stream_answer_multi`），每个故障小节独立

#### 4.3.5 超时与降级

- 拆解上限 4 个（`_MAX_SUB_QUERIES`），避免多故障时检索路数爆炸
- 拆解超时 20s → 按单故障整体处理，不让用户干等
- 单故障 ReAct 检索超时 60s；多故障并行检索整体超时 90s → 该组返回空，不阻塞整体回答
- 拆解失败 / 无多故障 → 整体按单故障走 ReAct 检索
- 检索失败 → 空案例，AnswerAgent 如实回答"未检索到"（不编造）

#### 4.3.6 多轮会话引导（分析 + 引导，`ExpertRepairAgent`）

> 专家模式在"拆解 + 分组分析"之上叠加了**多轮引导**：文件 `app/agents/expert_repair_agent.py`；端点 `POST /answer/expert`（首轮）+ `POST /answer/expert/step`（后续轮，SSE）。

**首轮（`/answer/expert`）事件序列**：

```
thinking → answer(共因/关联分析 + 维修优先级) → references
        → answer(分组五段式分析流, emit_done=False) → options(2-3 个方向) → done(携带 session_id)
```

**共因判定与优先级（对话中明确说出）**：LLM 基于各故障检索案例判断多现象是否**同根因**（如"油温高 + 锁模力不足 + 马达不转 ← 液压系统压力不足"），说明联动关系，并给出"先修哪个、为什么"；若共因解决后其他现象随之消失则直接结束（"一修带三好"）。

**后续轮（`/answer/expert/step`）**：用户反馈执行结果 → 检索（初始问题 + 当前反馈）→ 注入首轮分析 + 会话历史 → LLM 判断"已解决 / 部分解决 / 未解决"→ 生成【分析】+ 2-3 个新方向（按优先级，第 1 个为推荐），不重复已排查方向；全部解决 → 输出维修总结结束。

**会话与防膨胀**：Redis `expert_repair_session:{id}` 24h TTL；**30 步上限**；`chat_history` 超 25 条用 SessionSummarizer 增量压缩（保留最近 20 条原文，压缩失败保留原文）——与追踪维修同一套策略（详见 4.9）。

**单故障边界**：拆解后只有 1 个故障时不做"共因"判定（无多现象可比），首轮退化为"单故障定位分析 + 优先级"——同样生成 2-3 个方向选项并创建会话，多轮引导逻辑不变。

**面试点**：专家模式 = **问答 + 追踪的结合**——首轮给"真实案例的深度结论 + 排查入口"，后续像老师傅一样按反馈一步步带查；共因判定让多故障不重复修，方向选项带优先级推荐、用户可自选。

---

### 4.4 工单理解 Agent — `app/agents/ticket_agent.py`

#### 4.4.1 三步走

```
原始工单 (fault_description)
    │
    ▼
[Step 1] 标准化
    │   - 补全/修正故障码（多部件可返回多个，逗号分隔）
    │   - 提炼故障现象（50-200 字）
    │   - 推断根本原因
    │   - 建议维修步骤
    ▼
[Step 2] 分类
    │   - device_type: 注塑机/电机/CNC/冲床/传送带/锅炉/空压机...
    │   - fault_category: 机械/电气/液压/控制系统/操作失误/磨损老化/其他
    │   - tags: 3-5 个关键词标签
    │   - severity: LOW / MEDIUM / HIGH / CRITICAL
    ▼
[Step 3] 校验
    │   - completeness_score: 0-1（描述质量 + 字段填充率）
    │   - missing_fields: 缺失字段列表
    │   - validation_notes: 校验说明
    ▼
输出 TicketAnalysisResult → 主管/管理员审核确认
```

#### 4.4.2 工单审核流程（AI 回填 + 人工把关）

工单审核是"**AI 分析回填、自动收录，人做最终把关**"：

```
维修人员提交完成工单（complete）
    │
    ▼
[1] AI 标准化分析（仅当字段为空时回填缺失的故障码/现象/根因/方案）
    │
    ▼
[2] 自动提取知识（抽取 → 三层去重 → 发布 → 同步 Milvus）
    │       知识收录是自动的：人工无需手动建知识条目
    │
    ▼
[3] 主管/管理员人工把关（随时可退回 REJECTED）
    │
    ▼
最终状态：COMPLETED（通过） / REJECTED（退回补充）
```

- **为什么 AI 不自动放行**：维修工单是沉淀进知识库的数据源，一旦入库就会成为后续 AI 回答的依据——"错一条，污染一片"。所以最终把关权交给人（主管/管理员可通过 `REJECTED` 退回），AI 只负责把信息结构化、对空缺字段回填，降低人工核对成本。
- **"补全"的真实含义**：`complete` 提交时仅当字段为空（`not work_order.fault_code` 等）才用 AI 标准化结果回填故障码/现象/根因/方案，**不覆盖已填写的字段**；`tags` 标签由 AI 提取后直接覆盖（`if analysis.tags: work_order.tags = analysis.tags`）。
- **知识收录是自动的**：`_auto_publish_knowledge` 在提交完成时自动完成"抽取 → 三层去重 → 发布 → 同步 Milvus"，人工只在工单层面把关，不需要手动建知识条目；录入的知识条目标注 `source_type=WORK_ORDER` + `source_id` 可溯源回工单。

#### 4.4.3 集成多后端追踪（RAGFlow 默认）+ Redis 缓存

每次分析都打 trace（`app/core/langfuse_tracer.py` 统一抽象层，支持 RAGFlow / LangFuse / local 三种后端，`TRACING_BACKEND=ragflow` 默认，不可达自动降级 local 不影响业务）。

**先说清楚 RAGFlow 的定位（避免误解）**：RAGFlow 本职是 **RAG 平台**（文档处理 → 知识库 → 检索 → 问答），**不是追踪工具，它没有任何 LLM 可观测性功能**。本项目的"用 RAGFlow 做追踪"准确说法是：**复用了它的知识库能力**——把 trace JSON 当"文档"通过 REST API 上传到独立数据集 `ticket_traces`，用它的 Web 界面查看回放。相当于把它当 **trace 存档 + 回放库** 用（够用的下限），而不是当专业追踪平台用。

**RAGFlow 复用的能力边界**：

- ✅ 能做到（本项目实际使用）：trace 存档、Web 查看、按 trace_id 回放、失败降级本地日志
- ❌ 做不到（它没有这些概念）：trace 树 / span 嵌套、token 用量与成本统计、评估指标、性能告警、Prompt 版本管理——这些是 LangFuse 等专业 LLM 可观测性平台的职责

**为什么要加追踪**：一次问答链路很长（检索案例 → 记忆 → 生成 → 打分），纯日志还原不了"现场"——不知道当时问了什么、检索到哪些案例、模型回了什么、每步耗时多少。追踪给 LLM 调用做**业务级可观测性**：可回放、可排查、可评估回答质量。

**在项目中起什么作用**：

- 打点：`tracer.trace()` 自动记录 trace_id、事件流（enter/exit）、generation（prompt/response）、耗时、评分（score）
- 落库：trace 以 `trace_{id}.json` 文档上传 RAGFlow 独立数据集 `ticket_traces`（`permission=me`），与业务知识库物理隔离，**不参与检索、不污染知识库**
- 查看：登录 RAGFlow Web 界面回放每次问答完整链路
- 降级：RAGFlow 不可达自动降级本地日志，追踪挂掉不影响业务

**为什么复用 RAGFlow 而不是引入 LangFuse**（外包交付视角）：

- **客户硬性要求私有化**：工单、维修数据是工厂生产数据，客户不接受数据上公有云 → LangFuse 云这类 SaaS 直接排除
- **RAGFlow 本来就是交付方案的一部分**：系统要做 RAG 检索（问答查维修案例库），RAGFlow 已部署在**客户服务器**上，追踪只是多上传一种文档，交付清单零新增
- **两套原型交付让复用价值翻倍**：每多一个独立组件，每套客户环境都要部署/升级/排障，售后成本翻倍；复用已有组件是交付和售后的最优账
- **多工厂场景天然匹配多租户**：RAGFlow 租户隔离对应不同工厂/账号，trace 归属清晰
- **可替换不锁死**：`TRACING_BACKEND` 一键切换 RAGFlow / LangFuse / local，业务代码无感知
- **取舍**：复用方案只能做到"存档 + 回放"，没有 token 成本、评估指标等分析能力；当前需求（出问题能回放排查）够用，将来需要分析能力就切 LangFuse

**面试话术（一句话带过版）**：

> "每次分析调用都打 trace，走统一追踪抽象层（RAGFlow 默认、不可达自动降级本地日志）。注意：RAGFlow 本职是 RAG 平台，我们只是复用它的知识库存 trace 文档、Web 回放，不是拿它当专业追踪工具；专业分析（成本、评估）当前不需要，架构留了 `TRACING_BACKEND` 一键切换 LangFuse 的后路。"

**追问应对速查**：

| 追问 | 答法 |
|---|---|
| "RAGFlow 不是做 RAG 的吗，怎么当追踪用？" | 对，它本职是 RAG。我们不是拿它做追踪，是复用它的知识库存 trace 文档 + 界面回放——当存档库用 |
| "那为什么不直接用 LangFuse？" | 复用交付里已有的组件零新增；LangFuse 要每套客户环境新部署，售后成本翻倍；且架构可切换，需要时再切 |
| "RAGFlow 能分析成本、评估吗？" | 不能，它没有这些功能；我们只用了存档 + 回放，分析需求当前没有，将来切 LangFuse |
| "数据安全怎么保证？" | 全程私有化，部署在客户服务器，数据不出内网——这是客户的硬性要求也是交付前提 |
| "trace 会污染知识库吗？" | 不会，`ticket_traces` 是独立数据集，与业务知识库物理隔离，不参与检索 |

---

### 4.5 引导式追踪维修 — `app/agents/guided_repair_agent.py`

#### 4.5.1 对话式 vs 选项式

项目同时支持两种模式：
- **选项式**（`/guided-repair/start` + `/guided-repair/{session_id}/step`）：每步给 A/B/C 选项，维修员选一个 + 填操作结果
- **对话式流式**（`/guided-repair/chat`）：维修员发自然语言，AI 流式回复

#### 4.5.2 会话管理

- `session_id` 由 UUID 生成
- 会话状态存 Redis（`guided_repair_session:{id}`，24h TTL），Redis 不可用时降级内存缓存
- **30 步上限**（`MAX_STEPS`）：超过自动生成总结结束，长故障/复合故障也能引导到底
- **闲聊拦截**：与维修无关的消息不进排查会话（`_is_repair_irrelevant` 关键词白名单），回复固定引导语
- **会话过期提示**：加载不到会话明确提示"会话不存在或已过期，请重新开始"，不静默出错
- 长对话用 `SessionSummarizer` **增量压缩**成结构化摘要：`chat_history` 超 25 条 → 最旧部分并入 `history_summary`，保留最近 20 条原文（详见 4.9.4）

#### 4.5.3 异步流式实现

```python
async def achat(self, session_id, message, device_type):
    async for chunk in self.llm.astream(messages):  # 原生 async for
        yield chunk
```

**为什么用 `astream` 而不是 `stream`**：FastAPI 路由是 async 的，同步 `stream` 会阻塞事件循环；用 `koa-connect` 包装同步中间件会导致 ctx 泄漏（**项目踩过的坑**），所以原生异步重写。

---

### 4.6 钉钉机器人 LangGraph — `app/agents/robot_graph.py`

#### 4.6.1 主图 + 子图结构

```
主图 RobotGraph:
    router (占位节点)
        │
        ▼ 条件边 route_intent
    ┌───┬───────┬───────┬───────────┬───────┬───────┬────────┐
    │   │       │       │           │       │       │        │
   help create  todo  workorder  inventory  duty  repair   none
                    │
                    ▼ 子图（WoQueryGraph）
                  normalize → query
```

#### 4.6.2 意图路由三层策略

1. **(1) 快速通道**（零成本不经 LLM）：匹配"帮助/菜单/录入工单/WO-XXX 工单号"
2. **(2) LLM 分类**：处理 todo/duty/inventory/repair 等自然语言
3. **(3) 规则兜底**：LLM 失败时降级为关键词匹配

#### 4.6.3 工单查询子图

`WoQueryGraph` 作为主图的一个节点复用：
- `normalize` 节点：正则提取工单号，规范化为 `WO-YYYYMMDD-XXX`
- `query` 节点：调 `tools.query_work_order(no)` 查询并格式化

**为什么用子图**：工单查询是独立的两步流程，封装成子图后主图节点更聚焦，便于复用和扩展。

---

### 4.7 检索模型两级架构：bge-m3 召回 + Qwen3-Reranker 精排（推理服务化）

> 代码：`app/core/embedding_server.py`（独立推理服务，8010）+ `app/core/embeddings.py`（HTTP 客户端）+ `app/core/reranker.py`（精排客户端）

**两级模型架构（标准 RAG 分层）**：

| 阶段 | 模型 | 类型 | 作用 | 分数 |
|---|---|---|---|---|
| 召回 | bge-m3 | bi-encoder（dense 1024 维） | 全库粗筛，"别漏" | 余弦相似度 → Milvus ANN |
| 精排 | Qwen3-Reranker-0.6B | cross-encoder（decoder-only） | 对 top 30 候选细排，"要准" | sigmoid 归一化 0-1 → `rerank_score` |

#### 4.7.1 为什么召回用 bi-encoder、精排用 cross-encoder

- **bi-encoder**：问题和文档**分别编码**成向量，相似度=向量内积/余弦。可以**预先全库建向量索引**（Milvus ANN），查询毫秒级召回——但两段独立编码、语义交互浅，细粒度匹配（"注塑机温度高" vs "锅炉温度高"）区分弱
- **cross-encoder**：问题和文档**拼接成一个序列联合编码**，注意力在两者之间充分交互，打分准——但无法预索引，每条候选都要过一次模型，成本高，只能用于候选少（top 30）的精排阶段
- 所以标准做法是**两级流水线**：bi-encoder 广撒网 → cross-encoder 精修。召回扩到 `RECALL_TOP_K=30`（原 10），RRF 融合后取前 30 条进 reranker；**模型重排只排序、不过滤**（0.15 二次过滤仍按向量分数，模型分存独立字段 `rerank_score`，避免阈值语义混乱）

#### 4.7.2 推理服务化（进程内 → 独立服务）

- **为什么抽服务**：① 模型从进程内加载改为独立服务，后端启动快、不占模型内存；② 一个服务同时供 RAGFlow 等外部系统复用（`/v1/embeddings` OpenAI 兼容）；③ 模型升级/重启只动服务，后端零重启
- 接口：`POST /v1/embeddings`（OpenAI 兼容，批量编码）、`POST /v1/rerank`（query × documents 批量打分）、`GET /health`（双模型状态 + dim + 加载耗时）
- 客户端：`embeddings.py` 重写为 HTTP 客户端，**保留同名 API**（`encode_text`/`encode_texts`/`get_vector_dimension`）→ 全部调用点零改动；超时 30s + 重试 2 次 + 失败提示"先启动推理服务"
- bge-m3 仅用 dense 向量（1024 维，FlagEmbedding 已 L2 归一化）；sparse 稀疏检索本机不用（BM25 路已覆盖关键词匹配，职责不重复）

#### 4.7.3 降级链路（服务不可用 ≠ 系统不可用）

| 故障点 | 降级行为 | 恢复 |
|---|---|---|
| 推理服务整体不可用 | 检索自动降级 **BM25-only**（PG 关键词路 + RRF），跳过向量路与 0.15 向量过滤 | 服务恢复自动回弹 |
| reranker 不可用 | 回退规则 `weighted_rerank`（冷却熔断：连续失败 3 次 → 60s 内不再尝试） | 同上 |
| 单次编码失败 | 重试 2 次 → 该路失败 → 走 BM25 路 | 同上 |

设计原则：**降级不降可用性**——召回降级保"能答"，精排降级保"准头不崩"，接口不 500。

#### 4.7.4 双形态部署（本机 CPU = 降级形态，生产 = 标准形态）

> **面试关键表述**：本项目是**企业级交付，硬件是本机环境的约束，不是架构的约束**。同一套代码在两种形态下运行，差异只在模型跑在哪：

| 形态 | 部署 | 说明 |
|---|---|---|
| 本机开发形态（当前） | 推理服务 CPU 单进程，双模型约 5GB 内存，加载 3-6 分钟 | 功能完整，延迟更高（CPU 上 reranker top30 约 1-3s，可用 `RERANKER_ENABLED` 关精排） |
| 生产形态 | GPU 单机/多机：vLLM 或 Triton 托管双模型，推理服务多 worker/多副本 + 负载均衡 | 召回/精排延迟降到毫秒-百毫秒级；**代码零改动**，只改 `EMBEDDING_SERVER_URL` 指向生产服务 |

**模型选型与业务代码解耦**：推理服务独立承载模型，后端只通过 `EMBEDDING_SERVER_URL` 指向它；换模型 = 改配置（模型名/路径）+ 重灌向量 + 阈值重标定（见 7.4），零代码改动。

---

### 4.8 Milvus 向量存储 — `app/core/vector_store.py`

#### 4.8.1 集合 Schema

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(100) PK | UUID 字符串 |
| vector | FLOAT_VECTOR(1024) | 向量数据 |
| knowledge_id | INT64 | 关联 PG 知识条目 ID |
| title | VARCHAR(500) | 知识标题 |
| content | VARCHAR(65535) | 知识内容（截断） |
| device_type | VARCHAR(100) | 设备类型 |
| fault_code | VARCHAR(500) | 故障码（多个逗号分隔） |
| fault_tags | JSON | 故障标签数组 |

#### 4.8.2 索引配置

```python
{
    "index_type": "IVF_FLAT",
    "metric_type": "COSINE",
    "params": {"nlist": 1024}
}
```

**为什么 IVF_FLAT 而不是 HNSW**：
- IVF_FLAT 精度更高（无近似），适合工单库规模不大（seed 数据 200 条起步）的场景
- HNSW 召回更快但内存占用大，工单库规模上来后再切换
- `nlist=1024` 是经验值，建议 `nlist = sqrt(N) ~ 4*sqrt(N)`

**为什么 COSINE 而不是 L2**：
- 文本 embedding 用余弦相似度衡量语义接近度，与向量的绝对长度无关
- bge-m3 dense 输出已 L2 归一化，COSINE 等价于内积，性能最优

#### 4.8.3 懒加载

`_lazy_init()` 在首次 `insert` / `search` 时才连接 Milvus + 创建/加载集合。**避免启动时阻塞**。

---

### 4.9 会话管理 — `app/agents/session_agent.py` + `app/api/session.py`

#### 4.9.1 会话存储与摘要

| 层 | 存储 | TTL | 用途 |
|----|------|-----|------|
| 活跃会话 | Redis | 24h | 追踪维修 / 专家模式的实时对话上下文（`_SESSION_TTL = 24 * 3600`） |
| 钉钉用户映射 | Redis | 24h | staff_id → session_id 映射，跨班次隔离 |
| 历史会话 | 前端 localStorage | 永久 | 前端会话列表持久化（`saveSessions`，含 `_expertSessionId`） |
| 长对话摘要 | 按需生成 | - | 前端调 `/summarize` 即时压缩 / 后端保存时增量压缩，不占 Redis 长期空间 |

#### 4.9.2 SessionSummarizer 输出格式

```
## 会话摘要
用户核心问题：...
涉及设备/故障：...

### 已确认信息
- ...

### 诊断结论与处理方案
- ...

### 未解决的问题/待办
- ...
```

**为什么压缩**：LLM 上下文窗口有限（DeepSeek 64K），长对话超过窗口后无法继续，用摘要压缩能保持上下文连贯性。

#### 4.9.3 分场景会话策略（核心）

会话管理按"需要多少上下文"分档，**只在需要上下文的场景花存储和 token**：

| 入口 | 状态 | 存储 | 核心策略 |
|---|---|---|---|
| 智能问答 `/answer/stream` | **无状态** | — | 一次一答，不建会话、不存历史（快、稳、可并发） |
| 追踪维修 `/guided-repair/chat` | 有状态 | Redis `guided_repair_session:{id}` | 24h TTL、**30 步上限**、闲聊拦截、后端增量摘要压缩 |
| 专家模式 `/answer/expert` + `/expert/step` | 有状态 | Redis `expert_repair_session:{id}` | 24h TTL、**30 步上限**、首轮建会话 + 后续引导、后端增量摘要压缩 |
| 钉钉/MCP 追踪维修 | 有状态 | Redis `mcp/staff_guid:session:{staffId}` | staff→session 映射、24h 无对话自动开新会话、跨班次/跨天隔离 |

**为什么智能问答无状态**：问答是"一次性长回答"（五段式分析），语义由单次检索决定，不需要上下文；无状态 → 天然可并发、不占存储。有状态的两者（追踪/专家）都是**多轮交互依赖历史**（引导排查必须知道前面查了什么），必须带上下文。

#### 4.9.4 两层压缩（防止历史无限膨胀）

**① 前端压缩**：每个前端会话消息数达到 `COMPRESS_BATCH` 后，最旧的 user/assistant 消息调 `/session/summarize` 压缩成一条 `summary` 消息（问答/专家模式，追踪模式除外）。

**② 后端增量压缩**（GuidedRepairAgent / ExpertRepairAgent 各自的 `_maybe_compress_history`，保存会话时触发）：
- `chat_history` 超过 **25 条** → 最旧的 `(len-20)` 条与已有 `history_summary` 一起交给 SessionSummarizer 生成新摘要，会话只保留最近 **20 条原文**
- **增量式**：每次只压最旧部分，不重复压缩
- **压缩失败保留原文**（安全兜底，绝不让会话因压缩崩溃丢历史）

#### 4.9.5 三层上下文注入（有状态 Agent 通用）

```
[首轮分析/初始问题] + [已压缩的历史摘要 history_summary] + [最近 N 条原文] → 拼成 prompt
```

保证长会话下 LLM 仍能感知全局上下文，又不超 token。

#### 4.9.6 会话结构对比

| Agent | 会话内容 | 结束条件 |
|---|---|---|
| GuidedRepairAgent | device_type / initial_symptoms / chat_history / step_count / status | 用户反馈"解决"或 30 步上限 |
| ExpertRepairAgent | initial_question / sub_queries / faults / **first_analysis（首轮共因分析）** / chat_history / step_count | LLM 判定全部解决（all_resolved）或 30 步上限 |

#### 4.9.7 面试一句话总结

> "会话管理按上下文需求分档：问答无状态不花存储；追踪维修/专家模式有状态（Redis 24h + 30 步 + 后端增量摘要压缩 + 三层上下文注入）；钉钉在其上叠加 staff→session 映射做跨班次隔离；前端再做 localStorage 持久化 + 摘要压缩——前端压缩、后端压缩、步数上限三防线防止历史膨胀。"

---

## 5. 数据模型与存储设计

### 5.1 核心模型（`app/models/`）

| 模型 | 关键字段 |
|------|----------|
| `User` | id, username, role, dingtalk_user_id, phone |
| `Device` | id, name, model, device_type, location, status |
| `WorkOrder` | id, work_order_no, device_id, fault_description, fault_code, status(enum), priority, assignee_id, created_at |
| `KnowledgeItem` | id, title, content, device_type, fault_code, fault_tags(JSON), status(enum: draft/published), source_type, source_id |
| `ManualCodeEntry` | id, error_code, title, description, causes, solutions, manual_name, chapter, page（手册错误码权威库） |
| `WorkOrderProgressLog` | id, work_order_id, from_status, to_status, operator_id, source（工单状态流转留痕） |
| `FaultCodeMapping` | id, code, name, device_type, category（故障码映射） |
| `SparePart` | id, part_name, part_code, specification, stock_quantity, safety_stock, location |
| `DutySchedule` | id, user_id, date, shift, role |
| `LeaveRequest` | id, user_id, start_date, end_date, type, status |
| `Notification` | id, user_id, type, content, is_read |
| `WorkOrderImportBatch`（models/work_order_import.py） | id, filename, status, total_rows, success_rows |

### 5.2 工单状态枚举（含迁移历史）

工单状态用 PG ENUM 类型管理，迁移历史踩过的坑：

```python
# alembic/versions/b7c4d8e1f2a3_add_workorder_status_values.py
# 修复：PG 的 ALTER TYPE ADD VALUE 不支持 IF NOT EXISTS，重复迁移会报 "already exists"，
#       所以用 try/except 逐个 ADD VALUE，吞掉重复错误
for val in ['ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'ARCHIVED', 'STANDARDIZED', 'CLASSIFIED']:
    try:
        conn.execute(sa.text(f"ALTER TYPE workorderstatus ADD VALUE '{val}'"))
    except Exception:
        pass
```

### 5.3 双库分工

| 库 | 角色 | 数据 |
|----|------|------|
| PostgreSQL | 业务事实库 + BM25 全文检索 | 工单/设备/用户/知识/备件 |
| Milvus | 语义向量检索 | 工单/知识的向量索引 |
| Redis | 缓存 + 会话 | 引导维修会话（24h TTL）、查询白名单/LLM 兜底结果等缓存（检索结果本身未缓存，属规划项） |

**为什么不全用 PG pgvector**：项目早期考虑过，但 Milvus 专门为向量优化，IVF_FLAT/HNSW 等索引性能优于 pgvector。配置里保留了 pgvector 作为 fallback 选项（实际未启用）。

---

## 6. 部署与运维

### 6.1 Docker Compose 编排

```yaml
# docker-compose.dev.yml（start_all.ps1 一键启动使用，本项目基础设施编排；根目录 docker-compose.yml 是 RAGFlow 的，勿用）
services:
  postgres:    # v16, 宿主机 ${DB_PORT:-15432}:5432
  redis:       # v7, 宿主机 ${REDIS_PORT:-6379}:6379（当前 backend/.env 配 7379；重建容器后若映射变 6379 需同步改）
  etcd:        # v3.5.5, Milvus 元数据
  minio:       # 2025-02-28, Milvus 对象存储, 宿主机 ${MINIO_PORT:-9000}:9000 / 控制台 9001
  milvus:      # v2.4.15, 宿主机 ${MILVUS_PORT:-19530}:19530 / REST 9091
```

### 6.2 启动顺序

1. Docker 拉起基础设施容器（`docker compose -f docker-compose.dev.yml up -d`）
2. **启动推理服务**（8010）：`python -m app.core.embedding_server`，轮询 `/health` 就绪（双模型 CPU 加载约 3-6 分钟；`start_embedding_server.ps1` 自动轮询）
3. `alembic upgrade head` 执行数据库迁移
4. 向量类脚本依赖推理服务已就绪（内置连通性检查，未就绪直接报错退出）：`python scripts/sync_vectors.py` 同步 PG 知识到 Milvus；`seed_knowledge.py` / `import_manual_codes.py` 同理
5. `python scripts/seed_data.py` 灌种子数据（可选）
6. `uvicorn app.main:app --host 0.0.0.0 --port 18080` 启动后端（启动时仅探测 `/health`，不加载模型）
7. `npm run dev` 启动前端（Vite 端口 4173）

> 一键启动：项目根目录 `start_all.ps1`（端口冲突检查 + Docker → 启动推理服务并**轮询就绪（超时 300s）** → 后端 + 前端一起拉起；推理服务未就绪会明确报错退出，不会带病启动）

### 6.3 关键环境变量（`.env`）

```env
DEEPSEEK_API_KEY=sk-xxx          # 必填，否则 LLM 调用全失败
DEEPSEEK_MODEL=deepseek-chat
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=knowledge
MILVUS_LOG_CODE_COLLECTION=log_code   # 手册错误码向量集合
MILVUS_VECTOR_SIZE=1024
EMBEDDING_SERVER_URL=http://localhost:8010  # 推理服务地址（生产形态指向 GPU 服务集群）
EMBEDDING_MODEL_NAME=BAAI/bge-m3
RERANKER_MODEL_NAME=Qwen/Qwen3-Reranker-0.6B
RERANKER_ENABLED=true                        # 精排开关（可关，退回规则重排）
RECALL_TOP_K=30                              # 召回扩量（进 reranker 前的候选池）
FINAL_TOP_N=10                               # 重排后送 LLM 的条数
RETRIEVAL_COARSE_THRESHOLD=0.15              # 粗筛向量相似度下限（标定脚本按分数分布回填，见 7.4）
DEDUP_CANDIDATE_THRESHOLD=0.45               # 去重候选 / LLM 判定阈值（标定脚本回填，见 7.4）
DB_HOST=localhost
DB_PORT=15432                 # 宿主机映射端口（容器内 5432）
DB_USER=admin
DB_PASSWORD=admin123
DB_NAME=maintenance_db
REDIS_HOST=localhost
REDIS_PORT=7379               # 宿主机映射端口（容器内 6379）
HF_ENDPOINT=https://hf-mirror.com   # 国内镜像，避免 HF 下载超时
HF_HUB_OFFLINE=1                    # 模型已下载后开启，跳过在线检查
DINGTALK_MOCK_MODE=false            # 钉钉真实模式
TRACING_BACKEND=ragflow             # 追踪后端：ragflow | langfuse | local
BACKEND_PORT=18080                  # FastAPI 监听端口
```

---

## 7. 项目进行中遇到的问题与解决方案

> 面试被问"项目踩过什么坑 / 遇到过什么问题"时，**只讲这四个**——它们是项目演进的四条主线（检索策略设计 / ReAct 检索 / 知识闭环 / 模型服务化），每个都讲清"为什么这么设计 + 踩过什么坑 + 解决了什么"，比零散的环境坑更能体现工程深度。对应话术见 Q3（检索策略总纲）/ Q25（ReAct）/ Q26（知识闭环）/ Q11（bge-m3 召回）。

### 7.1 RAG 检索策略的设计（为什么这么设计 + 解决了什么）

**设计目标**：维修员用大白话描述故障（"3号注塑机锁模力不够"、"电机嗡嗡响"）也能命中历史案例；同时故障码/设备型号（SV0436、E3091）这种字面精确的内容能精准命中权威处理方案。

**① 为什么向量（余弦）+ 关键词（BM25）混合，缺一不可**
- **背景**：开发过程中用真实工单验证检索，翻车了两次——
  1. 维修员搜"注塑机嗡嗡响"，结果页返回一堆"温度高""锁模力不足"的案例，就是没有异响。查日志发现：向量路能理解"嗡嗡响"≈"异响"（语义对上了），但"嗡嗡响"三个字在知识库标题里根本没出现过，BM25 关键词路直接 0 命中——口语词和标题词对不上，单靠语义路就召回不全。
  2. 按故障码搜"SV0436"——向量路把它当成普通语义 token 匹配，召回的全是"伺服、报警"这类语义沾边但无关的泛案例，精确的故障码反而被语义稀释、命中不了。
- **向量擅长语义近似**："嗡嗡响"能匹配"马达异响"，"锁模力不够"能匹配"锁模压力不足"——解决"表述不同、意思相同"的召回
- **BM25 擅长字面精确**："SV0436"、"SIEMENS 840D"这种标识，向量编码后语义信息被稀释，必须逐字命中——解决"精确标识"的召回
- 结论：一个管"意思"、一个管"字面"，**缺一个就有盲区**，所以混合是设计起点，不是功能堆叠。

**② 为什么用 RRF 融合，而不是加权平均**
- **背景**：开发过程中先试的是加权平均融合（vector×0.5 + bm25×0.5），实测同一批 query：BM25 加权分能到几十、向量余弦只有 0.8，直接加权后向量分被完全淹没，排序被 BM25 大数值主导，双路都命中的案例反而排不上去。
- RRF 只看名次（`Σ 1/(60+rank)`），天然规避量纲；**双路都认同的条目排最前**（同一知识两路命中分叠加），这是 RRF 的核心价值
- k=60 是平滑参数，让名次差不过分悬殊

**③ 融合怎么落地（双库最多四路）**
- **双库四路**：**背景**——开发过程中接入手册库后，用"ALM-6401"实测发现走不到手册权威答案，因为知识库里根本没有这条记录。**设计**：知识库两路（向量 + BM25）总是走；问题含错误码（正则提取，零 LLM）时增开手册库两路（错误码精确 + 手册语义），最多四路
- **去重键**：**背景**——开发过程中第一次发现同一条工单双路都命中，结果里却出现两条一模一样的卡片（按 Milvus UUID / PG int 分开当了两条）；手册库加入后再次发现知识 5 号和手册 5 号被合并成一条、条目丢失。**设计**：`_dedup_key`（仅手册条目带 `M:{id}`）> `knowledge_id` > `id`——先统一两路口径，再隔离双库撞号
- **错误码置顶**：**背景**——开发过程中实测"SV0436"提问，精确命中的手册条目（score=1.0）排在第 5 位，被双路命中的泛相似案例压在下面。**设计**：融合过滤后按 `method == manual_code_exact` 置顶
- **严格过滤**：**背景**——见 ④ 多故障串味。**设计**：设备精确匹配 + 故障词命中（剔除跨设备/泛相似案例），空结果回退宽松 top2 防误伤

**④ 这套设计解决了项目进行时的哪些坑（= 设计动机的反面教材）**
- **"AI 答非所问"（准确率 30%）**：背景——开发过程中用 50 条真实工单提问验证，答案驴唇不对马嘴。根因是单路召回盲区 + 分数量纲乱加 → 混合 + RRF 解决"召不全、排不对"
- **多故障提问串味**：背景——开发过程中用"主轴过热 + 换刀故障"复合提问测试，故障小节引用了黑屏、输送设备电机过热等无关案例 → 严格过滤 + 规则预检切专家模式
- **故障码权威答案排不上去**：背景——开发过程中按错误码提问，权威手册条目排在泛案例后面 → 置顶修正
- **双库融合丢条目/张冠李戴**：背景——开发过程中接入手册库后知识库出现条目缺失/内容错配 → 复合去重键

**⑤ 一句话总结（可背）**：召回定"有没有"（向量+BM25 互补，一个管语义一个管字面）、融合定"排序对不对"（RRF 只看名次，双路认同的排最前）、过滤定"噪声别进来"（设备/故障词严格校验）——四层配合，检索准确率从 30% 提到 85%。对应话术见 Q3。

### 7.2 ReAct 检索 Agent（从固定检索到自主深挖）

**设计目标**：固定混合检索"一步到位"，但复杂/模糊提问一次检索召回不足（词不达意、表述不专业），需要 Agent 自主决定"换路检索、改写查询、补查条件"，多轮深挖直到质量达标。

**① 为什么从固定检索演进到 ReAct（而不是继续写死）**
- **背景**：开发过程中用模糊提问测试知识搜索页，用户问"3号机组怪响，查一下"这种大白话，一次检索结果不足或无关——查日志发现固定链路的路数（两路 → RRF → 过滤）编译时就定死了，结果不足时不会自己改写查询、不会换路，只能把次优结果原样返回。
- 固定检索的路数编译时就定了，结果不足时不会深挖
- 模糊提问（"3号机组怪响，查一下"）该走向量还是 BM25？该不该补设备/故障码条件？——这些决策依赖语义理解，规则写不全 → 交给 LLM 每轮决策，行动空间限定 6 个枚举动作（vector / bm25 / conditional / graph / rewrite / finish），避免 LLM 幻觉出不存在的工具名

**② 为什么用确定性步骤兜底（LLM 决策不能裸奔）**
- **require_hybrid 首轮强制双路**：**背景**——开发过程中跑检索日志做回归测试，发现第一轮 LLM 几乎总选 vector 且质量达标就 finish，BM25 路从未真正参与，"混合检索"名存实亡。**设计**：首轮确定性执行 vector+BM25，达标直接 RRF，不达标才进决策循环
- **质量判定用规则不调 LLM**：**背景**——开发过程中早期质量判定也调 LLM，一次检索额外多出 1~N 次 LLM 调用，延迟翻倍且判定不稳定（同样的结果有时判达标有时判不足）。**设计**：质量本质是客观的"数量 + 分数"（≥3 条且 ≥2 条高分或最高分 ≥0.7），规则快、稳、零成本
- **temperature=0.1 + MAX_ITERATIONS=5 + 规则兜底**：**背景**——开发过程中压测时出现过 LLM 决策连续失败、检索直接返回空结果的事故（坏一轮就全崩）。**设计**：低温度保决策可复现、硬上限防死循环、LLM 挂了检索不崩（首轮 vector / 不足 rewrite / 否则 finish）

**③ 怎么落地**
- 跨轮结果按 `knowledge_id` 去重累积（只增不覆盖），多轮搜到的新案例都保留
- scratchpad 记录每轮思考/行动/观察，作为可观测性输出（调试用）
- 专家模式多故障时各子查询并行跑 ReAct：`asyncio.gather + wait_for(90s)` 整体超时，单点失败对该故障降级，不拖垮整体回答

**④ 这套设计解决了开发过程中踩的哪些坑**
- 混合检索名存实亡（首轮早停）→ require_hybrid 兜下限
- 复杂提问召回不足、不会深挖 → 改写查询 + 换路补查
- LLM 决策失败 / 卡死 → 规则兜底 + 超时降级

**⑤ 一句话总结（可背）**：固定检索是"一步到位"，ReAct 是"按需深挖"——LLM 决策选路 + 规则兜底稳下限 + 硬上限防失控。代价是慢（多轮 LLM），所以只有知识搜索页和专家模式用，智能问答走固定混合（快、稳）。对应话术见 Q25。

### 7.3 工单 → 知识沉淀闭环（数据飞轮）

**设计目标**：知识库不靠人工维护——每次维修完成自动变成一条可检索知识；同时保证知识库不被重复条目污染（重复会稀释检索、霸榜）。

**① 为什么做自动闭环**
- **背景**：开发过程中知识库靠人工把工单转成知识——验收时抽查发现大量高频故障在知识库里没有对应条目（修完没人沉淀）；新设备接入没有历史案例，AI 直接说"未检索到"。老师傅离职后经验跟着流失。
- 人工维护知识库的痛：冷启动难（新设备没案例）、更新慢（修完忘了沉淀）、老师傅离职经验流失
- 工单完成（ARCHIVED）即触发：抽取 → 去重 → 发布 → 同步 Milvus，形成"维修 → 知识 → 检索 → 再维修"的数据飞轮

**② 为什么去重用"相似度筛候选 + LLM 判实质"，而不是相似度阈值直接判**
- **背景**：开发过程中最早用标题相似度阈值直接判重，测试时把"注塑机温度高-加热器坏"和"注塑机温度高-温控器漂移"两条不同原因的知识误判为重复拒收；人工复核时发现误杀率很高，有价值案例进不了库。
- 维修场景的核心矛盾：同设备同故障码可能**不同原因和方案**——相似度高 ≠ 重复
- 直接按相似度判重会误杀有价值案例，且误杀不可逆（好知识永远进不了库）
- 所以分层：相似度只筛候选（便宜、可召回），LLM 对比"故障原因 + 处理方案"判实质（贵、准确）——原因和方案都相同才算真重复

**③ 怎么落地（三层去重链 + 护栏）**
- **三层去重链**：**背景**——开发过程中发现纯故障码精确判重漏掉"标题改写但实质相同"的重复（同码不同措辞，如"电源模块保险丝熔断" vs "保险丝熔断处理"）。**设计**：故障码精确快路径（`fault_code LIKE`，零成本）→ 向量召回（`score_threshold=0.45`）→ 相似度 **≥ 0.55** 调 DedupAgent（LLM）
- **幂等护栏**：**背景**——开发过程中测试时发现前端重复提交完成工单（或事件重放），同一工单被抽取两次，知识库出现完全相同的两条。**设计**：`source_type + source_id` 幂等
- **发布即同步**：**背景**——开发过程中知识审核通过入库后检索搜不到，排查发现 Milvus 向量没同步。**设计**：`_sync_to_milvus` 发布即同步，新增知识立即可检索
- **保守不判重**：**背景**——开发过程中 DedupAgent 判定失败（JSON 解析异常/LLM 超时）时，若默认判重复会误杀好知识。**设计**：失败降级"保守不判重复"（宁可多收一条，不可误杀）

**④ 这套设计解决了开发过程中踩的哪些坑**
- 知识库重复污染（重复条目霸榜、稀释检索）→ 三层去重链
- 同单重复提取（事件重放/重复提交）→ 幂等护栏
- 知识入库但检索不到（向量不同步）→ 发布即同步

**⑤ 一句话总结（可背）**：闭环解决"知识从哪来"（自动沉淀），去重链解决"知识干不干净"（规则快路径省成本 + 向量筛候选 + LLM 判实质），护栏保证"宁可多收不可误杀"。0.45/0.55 的取值论证见 Q26 ⑤。

### 7.4 两级模型架构的工程化：推理服务化 + 阈值标定 + 降级链路

**设计目标**：检索是"bi-encoder 召回 + cross-encoder 精排"的两级架构——bge-m3 全库召回（bi-encoder，快、可建 ANN 索引）→ Qwen3-Reranker-0.6B 对 top 30 候选精排（cross-encoder，问题×候选联合编码，准），"广撒网 + 精细筛"（原理见 4.7）。模型推理与业务代码解耦、跑在独立推理服务（8010），工程上解决三个问题——**模型加载不阻塞业务、阈值不拍脑袋、服务挂了不拖垮检索**。

**① 为什么推理服务化**
- 模型从业务进程抽成独立服务（8010，OpenAI 兼容 `/v1/embeddings` + `/v1/rerank`）：后端启动快、不占模型内存；一个服务同时供 RAGFlow 等外部系统复用；模型升级/重启只动服务，后端零重启（见 4.7.2）
- 本机 CPU 双模型约 5GB、加载 3-6 分钟：后台线程预加载 + `/health` 如实报告 loading/ready/error，启动脚本轮询就绪（超时 300s 明确报错）

**② 坑 1——阈值不能拍脑袋（数据驱动标定）**
- 检索链路的阈值（`RETRIEVAL_COARSE_THRESHOLD` / `RETRIEVAL_VECTOR_THRESHOLD` / `DEDUP_CANDIDATE_THRESHOLD` / `DEDUP_LLM_THRESHOLD`）直接决定"该召回的召回不回来、该滤掉的滤不掉"，靠经验填不靠谱
- **解决**：全部阈值配置化 + 写 `scripts/calibrate_thresholds.py` 标定脚本——对代表性查询跑检索、统计 P5/P50/P85/P95 分位数分布，按分位数给建议阈值回填 `.env`（数据驱动，不拍脑袋）

**③ 坑 2——推理服务化后，服务挂 = 全站检索崩？**
- 编码/重排抽成独立服务后成单点，服务挂了会影响所有检索链路
- **解决：降级链路（降级不降可用性）**——embedding 不可用 → 自动降级 **BM25-only**（PG 关键词路照常返回，跳过向量路与向量过滤）；reranker 不可用 → 回退规则 `weighted_rerank`（关键词命中率打分，设备不匹配 ×0.2 压低）；服务恢复自动回弹，接口不报错

**④ 配套可观测**
- `/health` 暴露双模型加载状态 + 加载耗时；降级次数记结构化告警日志；生产 GPU 形态只改 `EMBEDDING_SERVER_URL` 指向 vLLM/SGLang 托管集群，代码零改动（见 4.7.4）

**⑤ 一句话总结（可背）**：两级模型架构（bi-encoder 召回 + cross-encoder 精排）的工程落地靠"**推理服务化（模型与业务解耦）+ 阈值标定（数据驱动）+ 降级链路（不因单点故障全挂）+ 可观测**"四件套——本机 CPU 是降级部署形态，生产 GPU 形态只改配置指向、代码零改动。对应话术见 Q11 / Q24。

---

## 8. 高频面试 Q&A

### Q1：你这个项目的核心创新点是什么？

**A**：核心是把企业维修工单沉淀成可检索的知识库，并通过 RAG + 多 Agent 协作的方式给维修员实时诊断建议。最大的创新是**专家模式的多故障拆解并行**：当用户问题同时涉及机械+液压+电气多个故障域时，FaultDecomposer 用规则预检 + LLM 把复合问题拆成多个单故障子查询，并行 ReAct 检索、按故障分组流式回答。这避免了单检索在跨域问题上语义被稀释的问题。

---

### Q2：为什么用 Milvus 而不是 pgvector 或 Faiss？

**A**：
1. **(1) Milvus 是专门的向量数据库**，IVF_FLAT/HNSW/DISKANN 等多种索引可选，性能优于 pgvector
2. **(2) 支持 JSON 元数据字段**，可以把 title/content/device_type/fault_code/fault_tags 直接存进 Milvus，检索时一次性返回，不需要回查 PG
3. **(3) 分布式架构**（etcd + MinIO），未来扩到亿级向量不需要换技术栈
4. **(4) pgvector 作为 fallback 保留**，配置里可切换，应对 Milvus 不可用的场景
5. **(5) 本项目具体用法**：`knowledge` / `log_code` 两个集合共用 `IVF_FLAT + COSINE` 索引（nlist=1024，检索 nprobe=16，详见 4.1.8）——中小数据量下 IVF_FLAT 参数直观、结果无损，是性价比选择
6. **(6) 支持标量过滤表达式**（`expr`）：向量检索时可叠加 `device_type == "注塑机"` 这类过滤，实现"先按条件过滤候选、再向量精排"，这是 pgvector 早期版本不具备的

Faiss 不选是因为它是库不是服务，没有持久化、没有高可用，需要自己包装。
> 追问补充：**"为什么不用 HNSW？"**——HNSW 图索引查询更快但内存占用大；本项目数据量级（千级~万级）下 IVF_FLAT 足够，且 `nprobe` 旋钮直观可调。百万级再切 HNSW（见 Q19）。

---

### Q3：你的 RAG 检索策略是怎么设计的？（检索策略总纲：召回 → 融合 → 过滤 → 验证，高频必问）

**A**：我的检索策略不是一步到位的，是开发过程中被真实问题逼着演进成"**召回 → 融合 → 过滤 → 验证**"四个阶段，每个阶段解决一类问题、职责单一。

**① 召回层（解决"召不全"）——双库最多四路**
- 知识库双路：Milvus 向量（语义近似）+ PG BM25（关键词精确）。故障码/设备型号这种字面内容，向量反而会失真，必须 BM25 兜底（为什么必须混合见 Q5）
- 手册库（log_code）加入后：问题含错误码 → 正则提取（零 LLM）→ 增开"手册错误码精确匹配（score=1.0）+ 手册语义向量"两路，最多四路
- 设计取舍：错误码**漏判是已知边界**（非规范格式提取不到 → 走 2 路，不启用手册权威答案，但不影响正确性）；**误判无害**（最多多查一路，结果里没有手册条目不影响回答）

**② 融合层（解决"排序对不对"）——RRF 名次融合**
- 四路分数量纲完全不同（cos 0~1 / BM25 无上限 / 精确匹配 1.0），直接加权会被大数值压垮 → 只看名次 `Σ 1/(60+rank)`（原理见 Q4）
- 去重键三级：`_dedup_key`（仅手册条目带 `M:{id}`）> `knowledge_id` > `id`
- **坑1（撞号）**：知识库和手册库主键都是 PG 自增 int，按 knowledge_id 会把"知识 5 号"和"手册 5 号"当成同一实体合并，丢条目/张冠李戴 → 复合键带来源前缀隔离
- **坑2（口径不一）**：向量路 id 是 Milvus UUID、BM25 路 id 是 PG int，按 id 合并会把同一条双路命中拆成两条，双路分加不上 → 统一按 knowledge_id

**③ 过滤层（解决"噪声别进来"）——阈值 + 模型精排 + 严格过滤**
- 通用过滤：score ≥ 0.15 + 剔除 `rrf_only`（只有 BM25 命中、无语义匹配的不可信）（阈值怎么定见 Q24；阈值已配置化 + 标定脚本按分数分布回填，见 7.4）
- **Qwen3-Reranker 模型精排**：召回扩到 top 30，cross-encoder 对"问题×候选"联合打分（`rerank_score`），只排序不过滤；服务不可用自动降级 `weighted_rerank` 规则重排（故障词权重 0.4、设备不匹配 ×0.2 压低）
- 问答/专家模式叠加**严格过滤**：设备精确匹配 + 故障词至少命中一个，剔除跨设备案例（"数控机床主轴过热"误召回"输送设备电机过热"）和同设备泛相似案例（"黑屏"）
- **坑3（串味）**：早期"单路向量 + 阈值太松 + 没有设备/故障维度校验"，多故障提问"主轴过热还有换刀故障"会混入黑屏、输送设备电机过热等无关案例 → 治理过程详见 Q22
- **坑4（权威条目名次吃亏）**：错误码精确命中（score=1.0）只在一路出现，RRF 按名次算排不过双路命中的泛相似案例 → 融合过滤后按 `method == manual_code_exact` 置顶
- 兜底：严格过滤为空回退宽松 top2，防误伤导致"未检索到"

**④ 验证层（解决"内容别编造"）——验证 Agent 三层把关**
- Gate（客观零 LLM）→ Judge（LLM 语义裁决）→ 存在性核对（DB 查库），Judge 不足触发 LLM 规划重搜策略的自主重搜循环 → 详见 Q23

**演进逻辑**：召回层决定"有没有"，融合层决定"排序对不对"，过滤层决定"噪声别进来"，验证层决定"内容别编造"——每层各管一件事。单独一层只能修一个维度的病，四层齐了，检索准确率才从 30% 提到 85%（踩坑复盘见 Q17）。

---

### Q4：你的 RAG 检索为什么用 RRF 融合？加权平均不行吗？

**A**：加权平均有量纲问题。向量检索返回的是余弦相似度（0-1），BM25 返回的是打分（可能几十几百），量纲不同直接加权会让 BM25 的大数值压垮向量分数。RRF 只用排名（rank）不用原始分数，公式 `score = Σ 1/(k + rank)`，k=60 是工业界经验值。这样无论原始分数量纲如何，只看排名，融合更稳健。

---

### Q5：向量检索和 BM25 检索各自的优势？为什么要混合？

**A**：
- **向量检索**擅长语义近似：用户问"电机嗡嗡响"能匹配到"马达异响"，因为语义相近
- **BM25 检索**擅长精确匹配：故障码"TEMP_HIGH_001"、设备型号"SIEMENS 840D"这种字面精确的内容，向量反而可能匹配不准

混合能取长补短。比如故障码查询走 BM25 精准命中，自然语言描述走向量语义匹配。

---

### Q6：你提到的"查询清洗"具体在做什么？为什么需要？

**A**：用户提问里经常带"怎么回事/可能/我你觉得/帮我看看"这些干扰词，这些词与设备/故障无关，但会严重影响语义向量。清洗流程：
1. 去标点
2. 保护固定故障词（"跳闸/报警"等，避免被误删）
3. 拆中文 span 和英文 span 分别处理
4. 前缀剥离（去掉"请问/帮我"）
5. 后缀剥离（去掉"怎么办/啊/呢"）
6. 中间高置信词替换（"怎么/可能/也许"即使在中间也安全删）
7. 单字中文丢弃

清洗后向量更"纯"，召回率显著提升。

---

### Q7：多故障并行检索时怎么避免子查询结果重复/互相污染？

**A**：每条子查询**独立走完整检索链路**，互相隔离：
1. **(1)** 每个子查询各自 `_filter_rerank_cases`（严格过滤 + 按 `_dedup_key`/`knowledge_id` 去重）——子查询之间不共享候选，不存在"跨查询重复合并"
2. **(2)** 参考案例带 `fault` 字段标明归属故障，跨故障汇总时全局按匹配度降序、截前 8，故障标签保留供前端分组
3. **(3)** 回答按故障分组（`stream_answer_multi`），每个故障小节只引用自己验证过的案例，不串味

所以"多故障并行"的关键不是"案例去重"，而是**拆解-隔离**：每个故障独立检索、独立过滤、独立回答，从源头避免复合问题一次检索互相稀释。

---

### Q8：多故障/并行检索失败时怎么降级？

**A**：三级兜底（真实实现）：
1. **拆解失败或无多故障**（如用户只问单个故障）：整体按单故障走 ReAct 智能检索
2. **多故障并行检索超时**（`timeout=60s`）：该组返回空，不阻塞整体回答
3. **单故障 ReAct 检索失败/超时**：空案例 → `AnswerAgent` 如实回答"未检索到相关案例"，绝不编造

任何一层失败都不会让整个请求挂掉，最差退化为"未检索到"的诚实回答。

---

### Q9：你怎么保证 AI 回答的内容不是瞎编的？

**A**：分两层——**Prompt 软约束 + 验证 Agent 机制保障**。

**① Prompt 硬约束（软约束层）**：
1. **只回答检索到的内容**，不得编造、推测
2. **如实回答无匹配**，不得强行拼凑
3. **分数由系统决定**，不得修改
4. **不提供通用建议**，不得使用案例之外的维修经验

前端 `references` 列表展示的 `knowledge_id / title / content / device_type / fault_code` 全是工单原文字段，LLM 没碰过。用户可以点开案例验证。

**② 验证 Agent（机制保障层，关键）**：见 Q23。核心是"**检索到才可见 → 可见才可说 → 说了必可查**"：
- 进入回答阶段的案例必须通过"Gate 客观检查 → Judge 语义可答性裁决 → **存在性核对（查库确认 knowledge_id / manual_code_id 真实存在）**"
- 回答只能引用"验证通过的案例集"，编造在输入侧就被堵死——LLM 没见过的东西写不出来
- 伪造 id 的引用会被存在性核对直接剔除

**③ 检索层过滤**：低于 0.15 的案例不送入 LLM；问答 / 专家模式叠加"设备类型精确匹配 + 故障关键词命中"严格过滤（见 4.1.4）。

---

### Q10：为什么用 LangGraph 而不是直接 if-else？

**A**：钉钉机器人意图路由早期是 if-else，后来改成 LangGraph StateGraph。优势：
1. **(1) 结构化**：每个意图是独立节点，条件边显式声明，比嵌套 if-else 清晰
2. **(2) 可扩展**：新增意图只需要加节点 + 加条件边，不动路由函数
3. **(3) 子图复用**：工单查询是两步流程（normalize + query），封装成子图后可作为主图节点复用
4. **(4) 可观测**：LangGraph 自带状态追踪，能看到每个节点的输入输出

---

### Q11：为什么召回模型选 bge-m3？bge-m3 强在哪？（完整故事见 7.4）

**A**：召回模型选了 bge-m3，核心是**召回更强 + 多语言/长文本更稳**：
1. **bge-m3 是 RAG 检索事实标准**：BAAI 出品，多语言（100+ 语言）检索模型，在 MIRACL（多语言检索基准）上名列前茅；中文维修场景效果优于同尺寸单语模型
2. **1024 维 dense 向量**：与 Milvus 集合 `MILVUS_VECTOR_SIZE=1024` 对齐，schema / 索引稳定
3. **长文本上限 8192**：维修案例 content 长，bge-m3 对长文本语义编码更稳（统一截断到 `MAX_VECTOR_CONTENT_LEN=500` 字进编码，见 7.4）
4. **训练方式**：MCL（多粒度对比学习）联合训练 dense / sparse / colbert 三种表示；只取 dense（1024 维，已 L2 归一化）——sparse 与 BM25 关键词路职责重叠，本机不用
5. **取向量方式**：`FlagEmbedding.BGEM3FlagModel.encode(return_dense=True)`，dense 向量自带归一化，Milvus COSINE 相似度 = 点积

> 阈值是"数据标定 + 上线调优"的工程参数：全部收进配置，由 `scripts/calibrate_thresholds.py` 按分数分布的分位数回填（见 7.4）；推理服务不可用时检索自动降级 BM25-only / 规则重排，服务恢复自动回弹（见 4.7.3）。

---

### Q12：为什么用 SSE 而不是 WebSocket？

**A**：
1. **(1) 单向推送够用**：AI 回答是服务端推送给客户端，不需要客户端实时回传
2. **(2) HTTP 兼容性好**：SSE 走标准 HTTP，不需要协议升级，防火墙友好
3. **(3) 自动重连**：浏览器原生支持断线重连
4. **(4) 实现简单**：FastAPI 的 `StreamingResponse` 直接支持

WebSocket 适合双向实时通信（如聊天室），AI 问答场景用 SSE 更轻量。

---

### Q13：你的工单审核流程是怎样的？AI 和人工各负责什么？

**A**：工单审核是"**AI 分析回填、自动收录，人做最终把关**"：

1. 维修员提交完成工单 → AI 标准化分析（仅当字段为空时回填缺失的故障码/现象/根因/方案）
2. 自动提取知识 → 三层去重 → 发布 → 同步 Milvus（知识收录是自动的，人工不建知识条目）
3. 主管/管理员随时可退回（REJECTED）把关，最终状态 COMPLETED（通过）或 REJECTED（退回补充）

**为什么 AI 不自动放行**：工单沉淀进知识库后会成为后续 AI 回答的依据——"错一条，污染一片"。所以 AI 只负责把信息结构化、对空缺字段回填、降低人工核对成本，最终把关权交给人（主管/管理员可退回），防止低质量工单污染检索。

---

### Q14：为什么 DeepSeek 而不是 OpenAI？

**A**：
1. **(1) 中文维修场景效果好**：DeepSeek 中文训练充分，维修术语理解准确
2. **(2) 性价比高**：DeepSeek API 价格是 GPT-4 的 1/10
3. **(3) 国内访问稳定**：不需要代理
4. **(4) 数据合规**：国内厂商，企业数据不出境

---

### Q15：你的专家模式（多故障并行）跟通用的 LangChain Agent 有什么区别？

**A**：通用 LangChain Agent 是**单 agent + tools** 模式，agent 自己决定调哪个工具。我的专家模式（`/answer/expert`）是"**拆解 + 并行隔离**"：
1. **(1) FaultDecomposer 拆解**：规则预检（零 LLM）+ LLM 把复合故障拆成单故障子查询，拆解器不直接检索
2. **(2) 每个子查询独立跑 `RetrievalAssistantAgent`**（ReAct 循环 + 检索工具），彼此**不共享状态、不共享候选**
3. **(3) 并行执行**：`asyncio.gather + asyncio.to_thread`（每个子查询跑独立线程的 ReAct 循环），各子查询同时跑，整体 `wait_for(90s)` 超时，不是串行
4. **(4) 分组流式回答**：`stream_answer_multi` 按故障分组输出，不是合成一份加权报告

通用 Agent 适合"一个 agent 自主完成复杂工具调用"；我的场景适合"**复合问题先拆开、再并行独立解决**"——拆解层管分、检索层管准、回答层管组。

---

### Q16：动态调度和多子 Agent 编排是一回事吗？

**A**：不完全是一回事，我诚实说明我的实现边界：
- **动态调度**：主 Agent 运行时用 LLM 生成调用计划，决定"调谁、按什么顺序、并行还是串行"——**我的项目没做这一层**
- **我的专家模式**是**静态两阶段流水线**：`拆解 → 并行检索 → 分组回答`，节点结构在代码里固定，类似 LangGraph 的静态工作流（节点和边编译时确定），区别只是拆解内容由 LLM 运行时决定（拆出几个子查询是动态的，但"拆→并→答"的骨架是固定的）

这样区分的好处：面试被追问"你的 Orchestrator 怎么动态决策"时，不会因为答不出不存在的实现而翻车。如果要升级成真正的主从编排（Planner 动态规划 + 专家池 + 合成），可以基于现在的 `retrieval_flow` 公共层扩展。

---

### Q17：你项目里最难的工程问题是什么？

**A**：**检索准确率**。早期开发过程中用户反馈"AI 答非所问"，排查发现：
1. 单路向量检索召回不全（口语"嗡嗡响"匹配不到标题里的"异响"）
2. 同会话上下文复用 → 第二次检索带第一次的上下文 → 结果跑偏
3. RRF 去重用错键 → 同条工单双路命中分不合并
4. SQL 缺 ORDER BY → 相关工单被截断
5. 用户提问带干扰词 → 向量被污染

每个问题单独看都不大，但叠加起来导致准确率从 30% 到 85%。**这告诉我 RAG 不是"接个 API 就完事"，工程细节决定成败**。

---

### Q18：你怎么评估 RAG 系统的好坏？

**A**：
1. **(1) 检索阶段**：手动构造 50 个典型问题，看 top_k 命中率（是否包含相关工单）
2. **(2) 生成阶段**：人工评估回答是否基于案例、是否瞎编、是否结构化
3. **(3) 端到端**：用户反馈（点赞/点踩），统计有用率
4. **(4) 多后端追踪**：每次调用打 trace（RAGFlow 默认 / LangFuse / local），看 token 消耗、延迟、错误率
5. **(5) 可观测报告**：验证 Agent 输出 report（每轮 sufficient / 剔除数 / 重搜策略 / 拦截率），量化"验证拦截率"与"sufficient 率"ROI

---

### Q19：如果工单库从 200 条 seed 扩到 100 万条，你的架构要怎么改？

**A**：
1. **(1) Milvus 索引切换**：IVF_FLAT → HNSW（百万级 HNSW 性能更好），`nlist` 调到 `4*sqrt(N)`，`nprobe` 按召回/延迟实测调优（现有 nlist=1024/nprobe=16 是千级数据量配置，见 4.1.8）
2. **(2) BM25 优化（三层渐进，见 4.1.7）**：先确认 pg_trgm 索引实际生效（`EXPLAIN` 看是否走 `Bitmap Index Scan`）→ 不够再按设备类型/时间分区 → 仍不够再换 PG 全文检索（`tsvector + tsquery + GIN 索引`）或上 Elasticsearch
3. **(3) 检索质量演进**：动态阈值（数据量大了固定 0.15 失真，精确查询 0.30 / 模糊查询动态百分位；阈值已配置化 + 标定脚本，见 7.4）；两阶段检索**已落地**（召回扩到 top 30 → Qwen3-Reranker 精排 top 10，见 4.7），百万级可进一步扩召回到 50~100 再精排——质量演进对"查得准"比纯索引更重要
4. **(4) Embedding 批量化**：`encode_texts` 改成真正的批量推理，不是循环 `encode_text`
5. **(5) 设备分片**：按设备类型预分片，检索 Agent 只查自己设备域的子集合
6. **(6) 缓存层**：高频 query 的检索结果走 Redis 缓存（`question + device_type` → 结果，知识库版本变更失效），避免重复计算 Milvus/LLM
7. **(7) 异步化**：检索改成真异步（SQLAlchemy async engine + asyncpg），避免阻塞事件循环

> 核心思路：**索引兜底（保持速度）是前提，质量演进（保持准确）才是重点**——数据量大了最难的从"检索慢"变成"检索不准"，所以 3 的优先级高于 2。

---

### Q20：项目里用 Redis 做了什么？

**A**：
1. **(1) 会话缓存**：钉钉机器人对话、引导式维修会话，24h TTL（`_SESSION_TTL = 24 * 3600`）
2. **(2) 备件库存查询缓存**：`spare_parts.py` 高频读走 Redis 短时缓存（30s），避免重复查库
3. **(3) 关键词提取 LLM 缓存**：`query_extractor` 相同 query 的 LLM 提取结果内存缓存 10 分钟，省 LLM 调用
4. **(4) 分布式锁**（规划中）：cache_service 已留"分布式锁基础"注释位，避免并发工单理解重复调用 LLM

所有 Redis 操作都用 `redis.asyncio` 全异步封装（cache_service），不走回调风格。

---

### Q21：如果用户的问题很模糊，专家模式拆不出子任务，怎么办？

**A**：兜底机制（专家模式）：
1. **(1) 规则预检不命中**：`_looks_compound` 判定非复合问题 → 单故障直通，**不产生多余 LLM 调用**
2. **(2) LLM 拆解失败 / 超时（20s）**：按原问题整体处理，走单故障 ReAct 检索
3. **(3) 检索无匹配**：验证 Agent Gate 拦截空候选，AnswerAgent 如实回答"未检索到相关案例，请提供更具体的设备型号或故障描述"
4. **(4) 空回答兜底**：不编造、不强行拼凑，给引导性提示

不会让用户拿到空回答，至少有引导性的提示。

---

### Q22：多故障提问（如"主轴过热还有换刀故障"）会检索串味，你怎么解决？

**A**：这是开发过程中真实踩过的坑——早期参考案例会混入"黑屏""输送设备电机过热"等无关案例。串味根因是：单路向量检索 + 0.15 阈值太松 + 没有设备/故障维度校验。治理分两条线：

**A（检索层 · 串味根治）**：
1. **强制混合检索**（`require_hybrid`）：首轮确定性执行 vector + BM25 双路，达标直接 RRF 融合，避免 Agent 第一轮选 vector 达标就早停，"混合检索"名存实亡
2. **设备 + 故障关键词严格过滤**（`_filter_rerank_cases`）：用 `query_extractor` 白名单从提问提取设备类型和故障词，案例必须设备精确匹配且至少命中一个故障词；严格过滤为空时回退宽松 top2 防误伤

**B（提示层 · 多故障检测）**：检索前用规则预检（连接词 + ≥2 个故障信号词，零 LLM 成本）检测复合提问，命中推送 `suggest_expert` 事件，前端提示"检测到多个故障现象，建议使用专家模式"，一键切换。专家模式会把问题拆成多个单故障子查询、并行 ReAct 检索、按故障分组回答，从源头避免多故障混在一起检索。

---

### Q23：你的"验证 Agent"是什么？为什么追踪模式没加全量验证？验证是不是多余的？（高频压力追问）

**A**：验证 Agent（`app/agents/verify_agent.py`）是"回答生成前对检索结果做三层把关"的组件，目标是**把"回答不编造"从 Prompt 软约束升级成机制保障**。

**① 三层把关**：
1. **Gate（客观，零 LLM）**：候选为空、错误码未命中手册——只拦事实，不设主观阈值
2. **Judge（语义，LLM）**：整体可答性裁决（sufficient / reason / missing）——边界由语义判断，不拍魔法数字
3. **存在性核对（DB 工具）**：knowledge_id / manual_code_id 逐一查 PG，伪造 id 直接剔除——硬边界

Judge 判不足时触发**自主重搜循环**（agentic loop）：LLM 规划重搜策略（改写查询 / 放宽设备 / 补手册路）→ 工具重搜 → 再 Judge，`max_iterations=2` 仅作资源护栏。这让它成为"真 Agent"（有工具调用 + 决策循环 + 停止条件），区别于普通 LLM 节点。

**② 为什么追踪模式不是每轮都全量验证？（应对"不一致"质疑）**

> 我的设计哲学是"**风险定价**"：验证强度与幻觉风险敞口匹配，不是均匀覆盖。
> - 智能问答是**一次性长回答**（五段式分析），编造空间大 → 放完整验证
> - 追踪维修是**短回答多轮对话**：每轮只输出一个动作（"检查抱闸 DC24V"），编造空间小；检索 query 每轮叠加用户真实反馈，上下文约束更强；且每轮检索走公共编排层（召回 → 过滤 → 模型精排）并过验证 Agent 复核（**未接完整重搜循环**，重搜是成本最高的环节）
> - 多轮对话本身是自纠错的：用户反馈进入下一轮检索，错误方向会被下一轮纠正
> - 所以追踪模式未接验证 Agent，靠低幻觉风险的短回答 + 规则过滤 + 对话自纠错兜底（当前没有"分级验证"，这是待补项）

**③ 验证是不是多余？（应对"浪费资源"质疑）**

> "没有验证也精确"是概率事件，不是保证——LLM 有固有幻觉率，证据不足时编造是已被反复验证的现象。验证把"可能幻觉"变成"结构上难幻觉"：回答引用的每个案例必须真实存在于知识库。
> 类比：**"代码能跑"不等于"代码正确"，需要测试；"回答流畅"也不等于"回答有依据"，需要验证。** 测试不是多余的，它把质量从"希望"变成"机制"。
> 而且验证不是均匀烧钱：大部分场景 Gate 零成本放行，只有存疑才投入 LLM——资源花在刀刃上。

**④ 收尾话术（一段背下来）**：

> 验证 Agent 的设计哲学是"风险定价"：长回答、关键决策放全量验证；短回答、多轮对话放轻量验证 + 依赖对话自纠错。至于"没验证也能精确"——精确在 LLM 场景是概率事件，我的验证把它变成结构保证：引用的每个案例都能在知识库里查到。这和"代码能跑不等于正确，所以要测试"是一个道理。

**⑤ 应对继续追问"怎么证明验证有用"（加分项）**：

> 我的验证 Agent 输出可观测的 report（每轮 sufficient / 剔除数 / 重搜策略 / 拦截率），可以统计"验证拦截率"和"sufficient 率"量化 ROI——它是可度量的质量组件，不是心理安慰。

---

### Q24：你的检索分数阈值 0.15 是怎么定的？为什么不用 0.2？（高频追问）

**A**：先澄清 0.15 在代码里的**真实定位**（它不是精确的相关度分界线）：
1. **两处用途**：`answer_agent.SCORE_THRESHOLD = 0.15` 是"无匹配判定线"（最高分 < 0.15 直接说未检索到）；`filter_rerank_cases` 里的 `score >= 0.15` 是"粗滤线"（剔除明显无关）。分数是**向量相似度**（bge-m3 余弦），不是 RRF 名次分、也不是 reranker 分——模型分存 `rerank_score` 独立字段，只排序不过滤，避免阈值语义混乱。

**① 为什么是 0.15（可解释的经验值）**：

> 我从检索结果分数分布里观测：真正相关的案例通常 **> 0.3**，弱相关在 **0.15-0.3**，明显无关的 **< 0.15**。所以 0.15 是"相关与明显无关"的分界处取值，而且我取的是**宽松值**——宁可多召回几条，让下游更精确的过滤去处理，而不是在粗滤层误杀。

**② 粗滤 vs 精筛的分层（关键论点）**：

> 0.15 不是"精准过滤"，它只是**粗滤保下限**——把明显无关的挡在门外；真正管准确的是下一层的**设备类型精确匹配 + 故障关键词命中**严格过滤。所以"0.15 为什么不是 0.2"对最终质量影响很小，它负责的是"别把垃圾送进精筛和 LLM"。

**③ 被追问"凭什么拍这个数？"的升级应答（加分项）**：

> 单靠数字阈值永远会被问"为什么是这个数"，所以我做了**双层**：数字阈值只做**便宜的粗滤**（省成本），**争议判断交给语义层**——验证 Agent 的 Judge 用 LLM 裁决"这些案例能否对这个问题给出可靠回答"，边界由语义定义，不是魔法数字。0.15 的定位是成本控制层的预筛，拦掉明显没救的，把"能不能答"的争议留给语义判断。

**④ 一句话总结（可背）**：

> **"数字阈值解决'明显'，语义判断解决'争议'——0.15 负责把明显无关的挡在门外，验证 Agent 负责裁决剩下的能不能答。"**

**⑤ 加分项（阈值工程化的回答）**：

> 阈值全部收进配置（`RETRIEVAL_COARSE_THRESHOLD` 等），由 `scripts/calibrate_thresholds.py` 标定脚本按分数分布的分位数回填——阈值是"数据标定 + 上线调优"的工程参数，不是拍脑袋的魔法数（过程见 7.4）。

### Q25：你的 ReAct 检索 Agent 是怎么设计的？跟固定混合检索比优势在哪？

**A**：知识搜索页（`/agent`）和专家模式单故障路径用的不是固定检索，而是一个真 ReAct 循环 Agent（`app/agents/retrieval_agent.py`）：

1. **(1) 行动空间**：`vector_search / bm25_search / conditional_query / graph_query / rewrite_query / finish` 六个动作，每轮 LLM（temperature=0.1 保证决策稳定）基于"当前查询 + 过滤条件 + 已获结果摘要 + 完整推理历史 scratchpad"输出 JSON 决策
2. **(2) 跨轮去重累积**：`all_results` 按 knowledge_id 只增不覆盖，多轮搜到的新案例都保留，不会重复累积
3. **(3) 规则质检不调 LLM**：`_evaluate_quality` 用规则判断质量（≥3 条 且 ≥2 条高分(≥0.6) 或 最高分 ≥0.7），省一次 LLM 调用
4. **(4) require_hybrid 强制混合（防呆设计）**：首轮不放开 LLM 自由选路，确定性执行 vector+BM25 双路，达标直接 RRF 融合——否则 LLM 第一轮选 vector 且质量达标就早停，"混合检索"名存实亡
5. **(5) 四级降级**：LLM 决策失败 → 规则兜底（首轮 vector / 结果不足则 rewrite / 否则 finish）；rewrite 失败强制结束；`MAX_ITERATIONS=5` 硬上限；最后一轮无论质量强制结束
6. **(6) 可观测**：scratchpad 完整记录每轮思考/行动/观察，作为调试和可观测性输出

**和固定混合检索的本质区别**：固定检索是"一步到位"（两路 → RRF → 过滤），ReAct 是"**按需深挖**"——结果不足时 LLM 自主决定改写查询（扩同义词）、换检索路（conditional/graph）、按设备/故障码补查，直到质量达标或 5 轮耗尽。代价是慢（多轮 LLM），所以只有知识搜索页和专家模式用，智能问答走固定混合（快、稳）。

**为什么这样能 work + 为什么不选其他策略（追问深挖）**：
1. **(1) 为什么让 LLM 决策而不是固定规则**：选哪条检索路需要理解查询语义（"嗡嗡响"该走向量还是 BM25？），规则写不全；LLM 决策 + 规则兜底，兼顾智能与稳定
2. **(2) 为什么行动空间限定 6 个动作**：不限定的话 LLM 可能幻觉出"不存在的工具名"；给死枚举（enum）+ 每轮只能选一个，等于给 LLM 搭脚手架，杜绝幻觉工具
3. **(3) 为什么质量判定用规则不用 LLM**：质量判定本质是客观的"数量 + 分数"（≥3 条、≥2 条高分、最高分 ≥0.7），规则一行就够；用 LLM 判反而慢、贵、还不稳定
4. **(4) 为什么决策 temperature=0.1**：检索决策要可复现，不能同一条 query 每次走不同路，否则用户看到的结果不稳定
5. **(5) 为什么不选其他方案**：
   - **纯固定混合检索**：快、稳，但"一条路走到黑"——结果不足时不会改写查询、不会换路深挖
   - **纯 LLM 全自主（无限循环）**：不可控、成本爆炸 → 用 `MAX_ITERATIONS=5` + 规则质检 + 逐层降级把它工程化
   - **LangChain 原生 Agent**：本质相同（都是 ReAct），但原生实现容易"首轮选一个工具、质量达标就早停"→ 我加 `require_hybrid` 强制混合 + 规则质检修正了这两个盲区

---

### Q26：你的"工单 → 知识"自动沉淀闭环是怎么设计的？怎么防止知识库被污染？（数据飞轮）

**A**：这是整个系统的"数据飞轮"——每次维修完成自动变成一条可检索知识，知识库不用人工维护。链路分四段：

**① 14 态状态机**（`models/work_order.py`）：
`DRAFT → SUBMITTED → ASSIGNED → ACCEPTED → ARRIVED → INSPECTING → IN_PROGRESS → COMPLETED → ARCHIVING → ARCHIVED / REJECTED`（保留 STANDARDIZED/CLASSIFIED/APPROVED 兼容旧数据）。每次流转写 `progress_logs` 全程留痕（from/to/operator/source）+ 更新维修员在办数。

**② 完成工单自动触发**（`api/work_orders.py` `_auto_publish_knowledge`）：
幂等（`source_type + source_id` 防同一工单重复提取）→ `KnowledgeExtractorAgent` 抽取（标题 15-30 字 + 现象/原因/排查/处理/预防五段式内容 + keywords）→ **去重检测** → 发布（PUBLISHED）→ 同步 Milvus 向量。（工单层面由主管/管理员最终把关，可退回 REJECTED——审核流程见 4.4.2）

**③ 三层去重链**（防止知识库被污染，核心难点）：
1. **快速路径**：故障码 + 设备精确匹配（`fault_code LIKE`）→ 命中直接调 LLM 判重
2. **向量语义召回**：Milvus 检索 `score_threshold=0.45` 召回相似候选
3. **LLM 判重**：相似度 **≥ 0.55** 的候选 → `DedupAgent`（LLM）对比"**故障原因 + 处理方案**"是否实质相同，只有都相同才算真重复
4. **补漏**：标题关键词 ILIKE / 内容关键词模糊匹配，命中也走 LLM 判重

**④ DedupAgent 判定规则**（`agents/dedup_agent.py`）：
忽略标题差异、故障码编号差异、设备类型细微表述差异（"PLC" vs "PLC系统"）；**仅标题相似不算重复**；判定失败时保守策略——**不判重复**（宁可多收一条，不可误杀）。

**为什么不用标题相似度直接判重**：维修场景下同设备同故障码可能有不同原因和方案（如"注塑机温度高"可能是加热器坏，也可能是温控器漂移），凭标题相似度会误杀有价值的新案例——所以相似度只用来"筛选候选"，真正判定交给 LLM 对比原因和方案。

**⑤ 为什么是这些值、为什么是这套策略（面试官重点追问的"为什么"，不只背数字）**

**（a）为什么向量召回用 0.45，不是 0.3 也不是 0.6？——召回线偏"宁滥勿缺"**
- 召回阈值决定候选集上限：相似度低于它的永远进不了候选，等于**永远不判重** → 真重复直接进库，污染不可逆
- 为什么不能更高（如 0.6）：维修知识表述差异大，**同因同方案但措辞不同**的两篇，向量相似度往往只有 0.5~0.6；召回线抬到 0.6 会漏掉这批"真重复但不像"的案例
- 为什么不能更低（如 0.3）：大量明显不相关的也进候选，matched 列表被噪声刷屏；且低分段向量分数本身不稳定（受检索参数、长文本平均影响大）
- 结论：**漏判（重复进库）的代价 > 多召回（多几个候选）的代价**，所以召回线向下放宽

**（b）为什么 LLM 判重门槛用 0.55，不是 0.4 也不是 0.7？——判重线是"成本线"**
- 0.55 是"值不值得花一次 LLM 调用"的成本线（一次判重 = 1 次 LLM 调用 + 30s 超时 + token 成本）
- 为什么不能更低（如 0.4）：0.45~0.55 区间的候选大多是明显不重复的，全部调 LLM → 成本爆炸、延迟升高
- 为什么不能更高（如 0.7）：相似度 >0.7 的两篇基本是同一篇的复述，**这个区间判重收益小**；而"疑似重复"的集中区恰恰在 0.55~0.7（表述不同但实质相同）
- 0.45~0.55 这段是"**召回但不花 LLM**"的观望区：进候选列表（可展示给用户），但不判重（`is_true_duplicate=False`）

**（c）为什么 0.75 / 0.85 是固定标记而不是实测相似度？**
- 规则路径（标题关键词 ILIKE / 故障码 LIKE 命中）本身没有"相似度"概念，代码传入固定标记只是为了 matched 列表有统一的分数字段可展示
- 0.85 > 0.75 是有意的：**故障码精确命中比标题关键词命中更可信**（故障码是业务主键级信号），标记分更高 → 规则命中的条目在候选里排更前

**（d）为什么用"相似度筛候选 + LLM 判实质"，而不是直接用相似度阈值判重？——策略核心**
- 纯相似度判重（如 ≥0.8 直接判重）的致命伤：**相似度高 ≠ 重复**。"注塑机温度高"可能是加热器坏，也可能是温控器漂移——标题几乎一样、原因方案完全不同，直接判重会误杀大量有价值案例
- 误杀不可逆：好知识永远进不了库，知识库变薄
- 所以分层：**相似度只筛选候选（便宜、可召回），LLM 只判定实质（贵、准确）**——便宜的先过滤，贵的后判定，各管各的

**（e）为什么不用其他判重策略？**

| 策略 | 判断 | 原因 |
|---|---|---|
| 编辑距离 / 字符串匹配 | 不用 | 只覆盖字面相同，同义改写、错别字、中英混排直接漏 |
| 纯关键词 ILIKE | 不用 | 要求关键词全命中，太苛刻 → 作为**补漏路径**保留（标题/内容关键词模糊匹配） |
| 纯 LLM 全量判重 | 不用 | 每个工单都调 LLM，成本高、延迟高 |
| 故障码精确 + LLM（已用） | 用 | 故障码是业务强信号，命中直接判重——**零成本快路径** |
| 向量召回 + LLM 判实质（已用） | 用 | 覆盖表述差异，兼顾成本与准确 |

**（f）被追问"数字能改吗？"**
- 能。0.45/0.55 是经验值不是推导值，改动的权衡就是上面"漏判 vs 成本"的曲线；先按构造的重复/非重复样例集调参，再看线上误判（误杀/漏判）微调
- 面试官看重的不是背数字，而是**知道每个值在权衡什么**；诚实说"经验调参 + 线上微调"，比假装有理论推导更可信
- 注意：文档早期版本有"0.65"的说法，**代码里没有 0.65**，以 0.45/0.55/0.75/0.85 为准。

**（g）被追问"这两个线是怎么划定的？"——划定方法 + 收尾话术（必背）**

划定方法不是拍脑袋，是**"先观测分数分布，再按代价分层定线"**三步：
1. **标注真重复样例**：拿一批人工确认的"真重复"（同因同方案但措辞不同，如"温度偏高" vs "温控偏高"）跑向量检索
2. **观测集中区**：这批真重复的相似度集中在 **0.5~0.6**——这就是"真重复长什么样"的实测分布
3. **按代价分层定线**：
   - **0.45 召回线**：真重复集中区下限 0.5 留 0.05 缓冲 → 管"**要不要进候选**"，宁滥勿缺（漏判进库污染不可逆，多召回只是多几个候选）
   - **0.55 判重线**：真重复集中区上沿 → 管"**要不要花一次 LLM**"（0.45~0.55 观望区召回但不判；≥0.55 疑似重复集中区才花 LLM；>0.7 基本是同文复述、判重收益小）
   - **0.85 不是实测**：故障码 LIKE 命中路径本身没有相似度概念，代码传固定标记分只为统一排序展示

**收尾话术（背下来）**：

> **"这两条线分管的不是一件事：0.45 管'要不要找'——召回线，宁滥勿缺；0.55 管'要不要花 LLM'——成本线，只在疑似集中区才花钱。中间 0.45~0.55 是观望区：进候选列表但不判重。线的位置不是拍的，是先拿标注样例看真重复的分数分布（集中在 0.5~0.6），再按'漏判污染不可逆 vs LLM 成本'的代价权衡定下来的。"**

---

### Q27：你的多轮对话/会话管理是怎么设计的？（追问：历史无限增长怎么办？）

**A**：会话管理按"需要多少上下文"分档，不是一刀切：

1. **(1) 分档策略**：
   - **智能问答无状态**：一次一答，不建会话（问答是长回答，语义由单次检索决定，不需要上下文）
   - **追踪维修 / 专家模式有状态**：多轮交互必须知道"前面查了什么"，所以 Redis 会话 24h TTL + 历史注入
   - **钉钉**在其上叠加 staff→session 映射，24h 无对话自动开新会话，跨班次隔离
2. **(2) 防历史无限膨胀（三防线）**：
   - **步数上限**：追踪/专家都限制 30 步，超限强制总结结束
   - **后端增量摘要压缩**：`chat_history` 超 25 条 → 最旧部分与已有 `history_summary` 一起交给 SessionSummarizer 生成新摘要，只保留最近 20 条原文——**增量式、失败保留原文兜底**
   - **前端压缩**：前端会话消息达 `COMPRESS_BATCH` 调 `/summarize` 压成 summary 条目
3. **(3) 三层上下文注入**：`[首轮分析/初始问题] + [已压缩摘要] + [最近原文]` 拼进 prompt——LLM 既能感知全局，又不超 token 窗口（DeepSeek 64K）
4. **(4) 专家模式特殊点**：首轮先做共因判定 + 维修优先级（对话中明确说出），多轮引导时 LLM 判断"已解决/部分解决/未解决"，共因解决后其他现象随之消失则直接结束——**问答 + 追踪的结合**（详见 4.3.6 / 4.9）

> 一句话：**只在需要上下文的场景花存储和 token；步数上限 + 后端增量摘要 + 前端压缩三道防线，让长会话永远可控。**

---

## 9. 项目亮点与可吹嘘的点

### 9.1 技术深度亮点

1. **(1) **两级模型精排的混合检索**：双库多路召回 + RRF 融合 + bge-m3/Qwen3-Reranker 模型精排（规则重排降级兜底），准确率显著高于单路
2. **(2) **查询清洗算法**：自研的中文 span 拆分 + 前后缀剥离 + 中间高置信词替换，专门解决中文干扰词问题
3. **(3) **专家模式拆解并行**：FaultDecomposer 规则预检 + LLM 拆解复合故障 → 各单故障子查询并行 ReAct 检索（require_hybrid 首轮强制双路）→ 分组流式回答，从源头避免复合提问的语义稀释与串味
4. **(4) **LangGraph 主图 + 子图**：智能问答主图意图路由（库存 > 聊天 > 故障）+ 3 个功能子图（CHAT/INVENTORY/FAULT），故障子图接验证 Agent，结构与钉钉 RobotGraph 同构
5. **(5) **验证 Agent 三层把关**：Gate（客观零 LLM）+ Judge（语义裁决）+ 存在性核对（DB 查库），Judge 不足时 LLM 规划重搜策略自主重搜循环（max_iterations=2），把"回答不编造"从 Prompt 软约束升级为机制保障
6. **(6) **模型服务化与降级链路**：bge-m3 + Qwen3-Reranker 独立推理服务（OpenAI 兼容、可复用），服务不可用自动降级（召回→BM25-only / 精排→规则重排），恢复自动回弹——**降级不降可用性**
7. **(7) **流式 SSE 五段式回答**：结构化输出 + 实时流式 + 案例来源严格保真
8. **(8) **双路索引对称支撑**：向量路 Milvus `IVF_FLAT + COSINE`（nlist=1024/nprobe=16，见 4.1.8）+ BM25 路 PG `pg_trgm` GIN 索引（见 4.1.6）——两条检索路都有索引支撑，数据增长不拖累任何一路；配合 `score_threshold=0.0` 全量召回 + 后段融合精排的分层设计
9. **(9) **错误码路由**：`extract_error_codes` 纯正则识别错误码（零 LLM）→ 决定 2 路/4 路切换 + 手册权威答案置顶（`manual_code_exact`）——用正则而非 LLM，零成本、可预测、无幻觉

### 9.2 工程实践亮点

1. **(1) **公共检索编排层**：retrieval_flow.py 统一智能问答 / 专家 / 钉钉 / MCP 的检索逻辑（双库召回 + RRF + 过滤 + 模型精排 + 错误码置顶），杜绝"检索逻辑写多遍"导致的策略漂移；专家/追踪维修的检索收敛回公共层，消除复刻漂移
2. **(2) **分级超时与降级**：拆解 20s / 单故障检索 60s / 多故障并行整体 90s，超时降级为"按单故障处理 / 空结果如实回答"，不挂死
3. **(3) **错误码置顶修正**：RRF 名次融合对单路权威条目（manual_code_exact）不公平，融合后按 method 置顶，避免"SV0436 精确命中"排不过泛相似案例
4. **(4) **SSE 事件协议统一**：专家模式与 /answer/stream 共用 thinking / references / answer / done 事件，参考案例带 fault 归属标签，前端零改动复用
5. **(5) **多后端追踪（RAGFlow 默认）**：`TRACING_BACKEND=ragflow`，trace 持久化到 RAGFlow 数据集，不可达降级本地日志
6. **(6) **Alembic 迁移健壮性**：迁移用 try/except 逐个 `ALTER TYPE ... ADD VALUE` 吞掉重复错误（PG 不支持 IF NOT EXISTS），避免重复迁移报错

### 9.3 业务价值亮点

1. **(1) **知识沉淀闭环**：工单 → 知识库 → AI 检索 → 新工单，形成正向循环
2. **(2) **AI 辅助人工把关**：提交完成时 AI 标准化分析并回填缺失字段，主管/管理员最终审核，审核效率提升、成本下降
3. **(3) **跨域复杂故障处理**：传统单检索无法处理的"机械+液压+电气同时出问题"场景
4. **(4) **钉钉企业集成**：OAuth + 机器人 + OA 审批，无缝接入企业现有工作流

---

## 10. 面试演示话术

### 10.1 30 秒电梯演讲

> 我做了一个面向制造企业的智能维修系统。核心是把维修工单沉淀成知识库，通过 RAG 让 AI 检索历史案例给出诊断建议。技术上用 FastAPI + LangChain + LangGraph + Milvus，最大的亮点是**专家模式的多故障拆解并行**：当用户问题同时涉及机械+液压+电气多个故障域时，FaultDecomposer 把复合问题拆成多个单故障子查询，并行 ReAct 检索、按故障分组流式回答。这避免了单检索在跨域问题上语义被稀释的问题，检索准确率从 30% 提升到 85%。

### 10.2 演示跨域问题的标准话术

> 假设维修员问："3 号注塑机锁模力不够出飞边，液压油温 65 度报警降不下来，熔胶马达不转电机嗡嗡响"。
>
> 这条 query 同时涉及机械、液压、电气三个域。如果用传统单检索，query 向量是三个域语义的"平均"，会被稀释，top_k 里三个域各混进来几条，分数最高的未必对应用户最关心的故障点。
>
> 我的专家模式是这样处理的：
> 1. **(1) FaultDecomposer 拆解**：规则预检（连接词 + ≥2 个故障信号词，零 LLM）命中复合提问 → LLM 拆成三个单故障子查询：机械域"注塑机 锁模力飞边"、液压域"注塑机 油温65度报警"、电气域"注塑机 熔胶马达不转嗡嗡响"，每个子查询保留设备上下文
> 2. **(2) 三个子查询并行检索**：各自独立跑 `RetrievalAssistantAgent`（ReAct 循环，首轮 `require_hybrid` 强制 vector+BM25 双路），互不共享候选，避免跨域污染
> 3. **(3) 各故障独立过滤**：设备精确匹配 + 故障词命中 + 错误码置顶，参考案例带 `fault` 归属标签
> 4. **(4) 分组流式回答**：`stream_answer_multi` 按故障分组输出，每个故障一个小节，前端分组展示——不做合成加权，各故障诊断独立、互不干扰

### 10.3 应对"这个项目缺啥"的提问

> 项目目前缺的主要有四块：
> 1. **(1) **评估体系不完整**：没有自动化的 RAG 评估指标（如 Ragas），目前靠人工抽样
> 2. **(2) **专家模式拆解粒度粗**：按故障现象拆解（机械/液压/电气），但没做设备类型级别的路由（如"注塑机专家"只检索注塑机域、并行数量 4 上限）
> 3. **(3) **知识库冷启动**：手册库已补错误码覆盖（精确 + 语义双路），但新设备手册缺失时 AI 仍无法回答，需要继续完善手册导入覆盖
> 4. **(4) **验证 Agent 覆盖不匀**：完整验证（Gate + Judge + 重搜 + 存在性核对）目前只接智能问答；追踪维修未接验证 Agent（仅 score≥0.15 过滤 + 重排），专家/钉钉入口也未接完整验证——这是"风险定价"的有意取舍，也是可继续补强的方向
>
> 这些问题我都有方案，只是当前 demo 阶段没做。

### 10.4 应对"动态编排能力"的提问

> 项目具备**静态工作流**和**专家模式流水线**两种能力：
>
> **静态工作流（LangGraph）**：
> - 智能问答主图意图路由（库存 > 聊天 > 故障）+ 3 个子图（CHAT/INVENTORY/FAULT）
> - 钉钉机器人的 LangGraph 意图路由（与智能问答同构）
> - 引导式维修的对话状态机
> - 工单理解 Agent 的"标准化 → 分类 → 校验"三步走
>
> 这些是**固定节点 + 固定边**的图，编译时就确定了。
>
> **专家模式流水线**：`拆解 → 并行检索 → 分组回答`，骨架静态，但拆解内容由 LLM 运行时决定（拆出几个子查询是动态的）。
>
> **真正的"运行时动态编排"（Planner 用 LLM 生成调用计划、Orchestrator 动态调度）我没有做**——这是有意的取舍：现有场景流程是稳定的，静态流水线可预测、易调试、失败路径清晰；等出现真正需要动态决策的业务流程，再基于 `retrieval_flow` 公共层升级。

---

## 附录 A：关键文件路径速查

| 模块 | 路径 |
|------|------|
| FastAPI 入口 | `backend/app/main.py` |
| 配置 | `backend/app/core/config.py` |
| Embedding | `backend/app/core/embeddings.py` |
| Milvus 封装 | `backend/app/core/vector_store.py` |
| 数据库 | `backend/app/core/database.py` |
| Redis 缓存 | `backend/app/core/cache_service.py` |
| LangFuse/RAGFlow 追踪 | `backend/app/core/langfuse_tracer.py`（多后端：RAGFlow / LangFuse / local） |
| 检索 API | `backend/app/api/search.py` |
| 检索工具集 | `backend/app/agents/tools.py` |
| 查询清洗 | `backend/app/agents/tools.py` (`clean_query_for_retrieval`) |
| 关键词提取 | `backend/app/agents/query_extractor.py` |
| ReAct 检索 Agent | `backend/app/agents/retrieval_agent.py` |
| 问答 Agent | `backend/app/agents/answer_agent.py` |
| 引导式维修 | `backend/app/agents/guided_repair_agent.py` |
| 工单理解 | `backend/app/agents/ticket_agent.py` |
| 钉钉路由图 | `backend/app/agents/robot_graph.py` |
| 智能问答 LangGraph 图 | `backend/app/agents/qa_graph.py`（主图 + 聊天/库存/故障子图） |
| **公共检索编排层** | `backend/app/agents/retrieval_flow.py`（问答/专家/钉钉/验证 Agent 共用） |
| **验证 Agent** | `backend/app/agents/verify_agent.py`（Gate + Judge + 重搜 + 存在性核对） |
| **故障拆解器** | `backend/app/agents/fault_decomposer.py`（专家模式拆解，`_MAX_SUB_QUERIES=4`） |
| 会话摘要 | `backend/app/agents/session_agent.py` |
| 知识模型 | `backend/app/models/knowledge.py` |
| 工单模型 | `backend/app/models/work_order.py` |
| 手册错误码模型 | `backend/app/models/manual_code.py` |
| **MCP Server** | `backend/app/mcp/server.py`（fastmcp，挂载 `/mcp`，`mcp_access_guard` 认证） |
| **MCP 工具实现** | `backend/app/mcp/tools.py`（与钉钉机器人共用同一来源） |
| Docker 编排 | `docker-compose.dev.yml`（基础设施编排，start_all.ps1 使用；根目录 `docker-compose.yml` 是 RAGFlow 的） |
| 依赖清单 | `requirements.txt`（项目根目录，唯一权威版本） |
| 一键启动 | `start_all.ps1`（项目根目录，端口冲突检查 + 全栈拉起） |
| 手册错误码导入脚本 | `backend/scripts/import_manual_codes.py` |

## 附录 B：演示用跨域 query

```
3号注塑机出问题了，锁模力明显不够，做出来的产品全是飞边；
液压油温一直65度报警降不下来；还有熔胶马达不转了，电机嗡嗡响。
```

调用方式（专家模式端点 `/answer/expert`，SSE 流式）：

```bash
# 注意：/answer/expert 需要登录鉴权，先登录（/api/v1/auth/login）拿 token，再加 Authorization 头，否则返回 401
curl -X POST http://127.0.0.1:18080/api/v1/search/answer/expert \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <你的token>" \
  -d '{"question": "3号注塑机出问题了，锁模力明显不够，做出来的产品全是飞边；液压油温一直65度报警降不下来；还有熔胶马达不转了，电机嗡嗡响。", "top_k": 5}'
```

预期 SSE 事件流（与 `/answer/stream` 协议一致）：
- `{"type": "thinking"}`：AI 正在拆解/检索
- `event: references`：参考案例列表，多故障时每条带 `fault` 归属标签（机械/液压/电气），全局按匹配度降序，最多 8 条
- `{"type": "answer", "content": "..."}`：流式回答片段，`stream_answer_multi` 按故障分组输出（每个故障一个小节）
- `{"type": "done", "confidence": ..., "sources_count": ...}`：完成事件

---

**文档结束。祝面试顺利！**
