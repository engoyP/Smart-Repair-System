# ReAct 循环检索详解

> 本文件说明项目中 **ReAct（Reason + Act）循环检索** 的实现与设计：
> 循环是什么、每轮怎么运转、达标标准、可选策略、结束与降级、在本项目中的定位。
>
> 涉及代码：[retrieval_agent.py](../backend/app/agents/retrieval_agent.py)、
> [search.py](../backend/app/api/search.py)、[Search.vue](../frontend/src/views/Search.vue)

---

## 1. 是什么

ReAct = **Reason（思考）→ Act（行动）→ Observe（观察）** 的迭代循环。
让 LLM 当"决策者"，**自主决定每一步查什么**：查不到就换策略/改写查询再查，直到结果满意或到达轮次上限。

与"固定管道"检索的本质区别：

| | 固定双路检索 | ReAct 循环检索 |
|---|---|---|
| 决策者 | 代码写死（向量+BM25 各查一次） | **LLM 每轮自主选择工具** |
| 查询 | 只用原始查询 | 结果差时 `rewrite_query` 改写再查 |
| 记忆 | 无 | scratchpad 记录每轮"思考/行动/观察" |
| 停止条件 | 一次跑完 | 质量达标 / LLM 选 finish / 5 轮上限 |

**比喻**：普通检索像"固定查两步"；ReAct 像老师傅查资料——第一次没查到 → 换个说法再查 → 换个角度查关联 → 按故障码精确筛，每步基于上一步结果决策，最多试 5 种办法，够了就收手。

---

## 2. 循环结构

```
for 迭代 in 1..MAX_ITERATIONS(=5):
    │
    ├─ ① 思考 _think       LLM 查看「当前查询 + 已获结果摘要 + 推理历史(scratchpad)」
    │                        → 决定下一步行动（JSON：action + 参数）
    │
    ├─ ② 行动              执行选定的检索工具（或改写查询、或宣布完成）
    │
    ├─ ③ 观察              记录本步结果，按 knowledge_id 去重累计进 all_results
    │
    └─ ④ 判断 _evaluate_quality
            达标 → break
            未达标（1~4 轮）→ 回到 ①
            第 5 轮 → 强制达标 break
收尾：多路结果 RRF 融合排序 → 返回
```

---

## 3. 每轮的标准（质量公式）

代码 [retrieval_agent.py:359-373](../backend/app/agents/retrieval_agent.py#L359-L373)：

```python
if len(results) == 0:
    return insufficient("无结果")
high_score_count = count(score >= 0.6)          # 高分条数
max_score = max(score)                          # 最高分
if len(results) >= 3 and (high_score_count >= 2 or max_score >= 0.7):
    return sufficient("结果充足")                # ★ 达标
if iteration >= 5:
    return sufficient("达到最大迭代次数")        # 到点强制交货
return insufficient("结果不足")
```

**达标标准（精确）**：结果 **≥3 条**，且满足任一：
- 至少 **2 条** 分数 ≥0.6；或
- **1 条** 最高分 ≥0.7

**设计意图**：
- 分数来自向量余弦 / RRF 分，即"语义上足够像"才算数——**光凑够 3 条低分案例不达标**
- "是否收手"由**规则公式把关**，不由 LLM 说了算——防止 LLM 偷懒提前结束或无限查下去

---

## 4. 可选策略（6 种）

枚举定义 [retrieval_agent.py:21-27](../backend/app/agents/retrieval_agent.py#L21-L27)：

| 策略 | 用途 | 适合场景 | 可带参数 |
|---|---|---|---|
| `vector_search` | 向量语义检索 | 模糊/口语化描述，按意思匹配 | top_k、score_threshold |
| `bm25_search` | 关键词精确检索 | 含明确关键词/故障码/设备编号 | top_k |
| `conditional_query` | 条件精确筛选 | 已确定设备类型/故障码/标签，按字段过滤 | device_type、fault_code、keyword |
| `graph_query` | 关联查询 | 查与某设备/故障相关的周边知识 | device_type、fault_code、top_k、exclude_ids（自动排除已查到的） |
| `rewrite_query` | 查询改写 | 结果不足时改写成更专业表述再查 | strategy（如 expand_synonyms） |
| `finish` | 完成 | 结果足够或不想查了 | — |

**LLM 的决策原则**（写死在 system_prompt）：
- 语义模糊 → `vector_search`；关键词明确 → `bm25_search`
- 用户给了设备/故障码 → 可追加 `conditional_query` / `graph_query`
- 首轮建议 vector + bm25 并行
- 质量不足**且有结果** → prompt 强制提示改用 `rewrite_query` 重试

**降级兜底 `_fallback_decision`**（LLM 思考返回非法 JSON 时）：
- 已有结果但不足 → 自动改 `rewrite_query` 重试
- 无结果 / 已到第 5 轮 → 自动 `finish`

---

## 5. 结束方式（3 种）

| 结束方式 | 触发条件 | 返回内容 |
|---|---|---|
| 质量达标 | ≥3 条 且（2 条≥0.6 或 1 条≥0.7） | 全部累计结果（RRF 融合排序） |
| 提前收手 | LLM 自主选 `finish` | 同上 |
| 到点交货 | 5 轮跑满，强制判达标 | **前几轮累计的所有结果**，照常返回 |

**不会因为超轮次而报失败**——"5 轮是耐心上限，不是失败上限"。
- 有结果（哪怕 1 条）：正常返回案例列表
- 完全没查到：返回空列表 → 前端友好提示"未找到相关案例，建议换关键词/补充型号或故障码"

真正的失败路径只有两条：LLM 思考失败（自动降级，不失败）、查询改写失败（返回改写前已累计的结果）。

---

## 6. 在本项目中的定位

**唯一使用入口：知识库搜索页（Search.vue，页面名"AI 知识问答"）**

前端 [Search.vue:240-247](../frontend/src/views/Search.vue#L240-L247)：
```js
const payload = { query: text, device_type: null, fault_code: null, top_k: 8, mode: 'agent' }
await request.post('/search/agent', payload)
```

后端接口 `POST /api/v1/search/agent`（[search.py:180](../backend/app/api/search.py#L180)）→ `RetrievalAssistantAgent.search()`。

页面展示 ReAct 的独特产出：`strategies_used`（用过的策略）、`rewrite_count`（改写次数）、案例来源卡片、检索耗时。

**与其他入口分工**：

| 入口 | 定位 | 检索方式 |
|---|---|---|
| AI 知识问答（Search.vue） | 一次性捞历史案例、**可追溯** | ReAct 循环 |
| 智能问答（AiAssistant / /answer） | 直接给结论式回答 | 固定双路 + AnswerAgent |
| 追踪维修 | 一步步引导排查 | 轻量双路 + GuidedRepairAgent |
| 钉钉机器人 | 移动端快捷入口 | robot_graph 按意图分发 |

> 注意：四者**共用同一个知识库**（PG `knowledge_items` + Milvus），差异只在检索流程复杂度与 Agent 分工。

**ReAct 在本项目的作用**：
1. 让模糊口语（"那台机器老报警"）也能查到案例——`rewrite_query` 改写成专业表述
2. 查得全、查得准——LLM 动态换策略 + 明确质量达标线
3. 结果可追溯可核验——展示策略、改写次数、案例来源卡片，不是黑盒结论

---

## 7. 关键参数速查

| 参数 | 值 | 位置 | 含义 | 依据 |
|---|---|---|---|---|
| MAX_ITERATIONS | 5 | retrieval_agent.py:66 | 最多轮数，防死循环/超时 | 工程取舍：多轮收益递减，5 轮足够 |
| MIN_RESULTS_FOR_QUALITY | 3 | retrieval_agent.py:67 | 结果条数下限 | 经验值：≥3 条才有参考价值 |
| MIN_SCORE_FOR_QUALITY | 0.6 | retrieval_agent.py:68 | 高分线 | 经验值：余弦 ≥0.6 算语义相关 |
| 达标高分线 | 2 条≥0.6 或 1 条≥0.7 | _evaluate_quality | 质量达标 | 经验值：避免单条侥幸达标 |
| LLM temperature | 0.1 | retrieval_agent.py:80 | 决策稳定性 | 低温度让决策可复现 |
| 收尾融合 | rrf_merge(k=60) | search() | 多路结果排序 | RRF 论文（SIGIR 2009） |

---

## 8. 与固定双路检索的对比（回到全局）

```
固定双路（问答/追踪维修）        ReAct（搜索页）
  一次查询 ────────────→   多轮决策（≤5 轮）
  vector+BM25 固定            LLM 选策略 + 可改写
  无反馈                     有质量反馈回路
  快、稳、严格引用            全、准、可追溯
```

**设计哲学**：搜索页要"查得全、查得准"（用 ReAct 多轮试错）；问答/追踪维修要"快、稳、不超时"（用固定双路）。两套检索共用同一份知识库与同一套 RRF/重排算法。
