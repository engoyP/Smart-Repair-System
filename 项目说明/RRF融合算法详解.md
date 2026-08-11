# RRF 融合算法详解

> 位置：`backend/app/agents/tools.py#L429-L514`
> 作用：把多路检索结果合并成一份排好序的列表。
> 适用：知识检索（`/hybrid`、`/agent`）、智能问答（`/answer/stream`）、专家模式（`/answer/expert`）的检索融合阶段。
> ⚠️ **路数演进**：早期是两路（知识库 向量 + BM25）；手册库（log_code）加入后变为**双库最多四路**（知识向量 / 知识BM25 / 手册错误码精确 / 手册向量），并新增复合去重键 `_dedup_key` 防撞号——详见「十点五、双库四路融合」。下文 一~九 以两路为例讲解 RRF 原理，四路的扩展规则一致。

---

## 一、先看一个最简例子（10 秒理解 RRF）

假设知识库里只有 3 条知识：`12号《注塑机温度偏高》`、`33号《注塑机料筒故障》`、`45号《电机异响》`。
用户搜"注塑机温度过高"，两路各自召回：

| 知识 | 向量路名次 | BM25 路名次 |
|---|---|---|
| **12号** | 第 1 | 第 1 |
| 33号 | 第 2 | 第 2 |
| 45号 | 没召回 | 第 3 |

RRF 打分（k=60）：

```
12号 = 1/(60+1) + 1/(60+1) = 0.0164 + 0.0164 = 0.0328   ← 双路都第一，夺冠
33号 = 1/(60+2) + 1/(60+2) = 0.0161 + 0.0161 = 0.0322
45号 =           1/(60+3)              = 0.0159   ← 只有一路，垫底
```

**结论：双路都认同的知识（12号）排最前。** 这就是 RRF 的全部秘密。

---

## 二、核心思想（30 秒版）

RRF（Reciprocal Rank Fusion，倒数排名融合）**不看分数、只看排名**：

```
某条在某路的分 = 1 / (k + 该路名次)      # k = 60（平滑参数）
同一知识双路都命中 → 两份分累加 → 自动排最前
```

### 为什么不看分数？

| | 向量路 | BM25 路 |
|---|---|---|
| 分数是什么 | 余弦相似度 | 关键词加权分 |
| 取值范围 | 0 ~ 1（如 0.82） | 无上限（如 5.2） |
| 能直接比吗 | —— | ❌ 口径完全不同 |

两路分数不可比，但"排名"都是"第几"，天然可比。所以 RRF 把分数全扔掉，只比排名。

### 公式速查表

| 名次 | 单路得分 | 双路都命中 |
|---|---|---|
| 第 1 名 | 1/(60+1) ≈ 0.0164 | 0.0328 |
| 第 2 名 | 1/(60+2) ≈ 0.0161 | 0.0322 |
| 第 5 名 | 1/65 ≈ 0.0154 | 0.0308 |
| 第 10 名 | 1/70 ≈ 0.0143 | 0.0286 |

> k=60 的作用：平滑差距。排名 1 和排名 2 的分差只有 0.0003，不会因为"差一名"就天差地别。

---

## 三、函数签名与输入输出

```python
def rrf_merge(result_sets, k=60, top_n=10):
    """
    result_sets: 多路结果列表的列表（每路一个子列表）
                 [[向量路结果...], [BM25路结果...]]
    k:           平滑参数，默认 60，一般不用改
    top_n:       最终返回前几条，默认 10
    """
```

### 输入长什么样（真实数据结构）

```python
result_sets = [
    # ── 第 1 个子列表：向量路（Milvus 召回，id 是 UUID）──
    [
        {"id": "3f9a2c11-...", "knowledge_id": 12, "title": "注塑机温度偏高处理", "content": "现象：温度持续偏高...", "score": 0.82, "method": "vector_search"},
        {"id": "7b1e4d55-...", "knowledge_id": 33, "title": "料筒温控失效处理",   "content": "料筒加热不均...",   "score": 0.61, "method": "vector_search"},
    ],
    # ── 第 2 个子列表：BM25 路（PostgreSQL 召回，id 是整数主键）──
    [
        {"id": 12, "knowledge_id": 12, "title": "注塑机温度偏高处理", "content": "现象：温度持续偏高...", "score": 5.2, "method": "bm25_search"},
        {"id": 33, "knowledge_id": 33, "title": "料筒温控失效处理",   "content": "料筒加热不均...",   "score": 3.1, "method": "bm25_search"},
        {"id": 45, "knowledge_id": 45, "title": "电机异响排查",       "content": "轴承磨损导致...",   "score": 2.0, "method": "bm25_search"},
    ],
]
```

> **注意**：这个输入不是全量知识库，而是两路各自**先召回 top_k 条**的候选集（见"六、上下游"）。

---

## 四、三个关键 id（最易混淆，务必先搞懂）

一条知识在系统里存了**两份**，因此有两套标识：

```
PostgreSQL（正本·档案室）          Milvus（副本·储物柜）
┌──────────────────┐          ┌──────────────────────────┐
│ id: 12 (整数主键) │          │ id: "3f9a..." (UUID 柜号) │
│ 标题/内容...       │          │ knowledge_id: 12 (抄来的学号) │
│                   │          │ 标题/内容/向量...         │
└──────────────────┘          └──────────────────────────┘
```

| 字段 | 向量路值 | BM25 路值 | 备注 |
|---|---|---|---|
| `item["id"]` | UUID 字符串 `"3f9a..."` | 整数 `12` | 两路口径不一致，**不能当合并键** |
| `item["knowledge_id"]` | 整数 `12` | 整数 `12` | 两路一致 = 身份证号，**合并键** |
| `item["method"]` | `"vector_search"` | `"bm25_search"` | 来源路标签 |

> **比喻**：`knowledge_id` = 学号（两路都有、一致）；`id` = 储物柜号（档案室和体育馆各编各的）。
> **代码**：`item_id = kid or raw_id` → 优先认学号 → 同一知识合并成一条，双路分才能累加。

### 如果不统一去重键会怎样？

拿 `id` 当合并键 → 同一个 12 号被当成两条（一条是 `"3f9a..."`，一条是 `12`）→
双路分合并不上 → 12 号只有 1/61 而不是 2/61 → 排序错乱，用户还会看到**两条一模一样的知识卡片**。

### 4.5 第四个 key：`_dedup_key`（双库复合键，防撞号）

手册库加入后，`knowledge_id` 也不够用了——**知识库和手册库的主键都是 PG 自增 int**：

```
知识库（knowledge_items）   id=5  → 《注塑机料筒故障》
手册库（manual_code_entries） id=5  → 《SV0436 伺服放大器过流》
```

两个 id=5 是**完全不同的实体**，但 `knowledge_id` 字段两库都用同一个自增序列的 id。若继续按 `knowledge_id` 去重，手册 5 号会被当成知识 5 号的"双路命中"合并 → **丢条目 / 张冠李戴**。

**解决**：融合前给每条打复合键 `_dedup_key`，用**来源前缀隔离**：
- 手册条目 → `M:{manual_id}`（如 `M:5`）
- 知识条目 → `K:{knowledge_id}`（如 `K:5`）

合并键优先级：`_dedup_key` > `knowledge_id` > `id`。**同库内才按 id 判重，跨库永不撞号**。

> **类比**：`_dedup_key` = "学校名 + 学号"（清华5号 ≠ 北大5号）；`knowledge_id` = 裸学号（两校都从 1 编起，会撞）。

---

## 五、完整代码流程走查（9 步，带详细注释）

### Step 0：先看整体骨架

```python
def rrf_merge(result_sets, k=60, top_n=10):
    scores = {}                                  # ① 记账本
    for result_set in result_sets:               # ② 外层：按"路"循环
        for rank, item in enumerate(result_set, start=1):  # ③ 内层：按"条"循环
            ...                                  # ④ 取id → ⑤ 告警 → ⑥ 打分 → ⑦ 记分 → ⑧ 择优
    merged = sorted(...)                          # ⑨ 排序
    ...                                          # ⑩ 截取 + ⑪ 防御去重
    return unique
```

### Step 1：开记账本（L453）

```python
scores = {}
# 结构：{知识id: {"rrf": 0.0, "vector_score": 0.0, "item": {...}}}
# 三个字段各管一件事：
#   rrf          → 排序用的内部分（跨路累加）
#   vector_score → 展示给用户的分（统一用向量相似度 0~1）
#   item         → 最终输出的内容模板（保留单路分最高的那份详情）
```

### Step 2：双重循环（L455-L457）

```python
for result_set in result_sets:                              # 外层：一趟 = 一路
    for rank, item in enumerate(result_set, start=1):       # 内层：一次 = 1 条
        # rank 从 1 开始（第 1 条名次就是 1）
```

- 外层一轮 = **一整路**（向量路 1 轮、BM25 路 1 轮）
- 内层一次 = **1 条**（每次迭代处理 1 条，相当于"记账一次"）
- 注意：循环本身**不产出结果**，只负责往 `scores` 里记账；最终结果在循环结束后统一排序产生

### Step 3：取 id、跳过脏数据（L458-L462）

```python
raw_id = item.get("id")            # 向量路 → "3f9a..."（UUID）；BM25路 → 12（整数）
kid = item.get("knowledge_id")     # 两路 → 都是 12（数据库主键）
item_id = kid or raw_id            # 优先用 knowledge_id；没有才退回 id
if item_id is None:
    continue                       # 连一个 id 都没有的脏数据 → 直接跳过不记账
```

> 举例：向量路的 12 号，`raw_id="3f9a..."`、`kid=12` → `item_id = 12`（用了 kid）。
> 举例：BM25 路的 12 号，`raw_id=12`、`kid=12` → `item_id = 12`。
> → 两条最终都归到同一个键 `12` 上，这正是我们要的。

### Step 4：一致性告警（L464-L474）—— 哨兵

```python
method = item.get("method", "unknown")   # 取来源路标签，没有就给 "unknown"（不报错）
if raw_id is not None and kid is not None and str(raw_id) != str(kid):
    # 触发条件：id 和 knowledge_id 同时存在，且不相等
    # 例：向量路 12号 → "3f9a..." != "12" → 触发（正常现象）
    # 例：BM25路 12号 → "12" == "12"      → 不触发
    if method not in _RRF_ALERTED_METHODS:      # 这条路之前告警过吗？
        _RRF_ALERTED_METHODS.add(method)        # 没告警过 → 记下"这条路已提醒过"
        logger.warning(...)                     # 打一条警告日志
```

**为什么需要 `_RRF_ALERTED_METHODS`？**
向量路每一条结果都会触发这个条件（成百上千条）。如果没有这个集合，一次融合会刷几百条告警日志。
有了它 → 每个方法（如 `"vector_search"`）**整次运行只警告 1 次**。

**它在保护什么？** 对未来的开发者说："现在这路 id 和 knowledge_id 对不上（UUID vs 主键），RRF 已帮你统一了。但以后你**新增检索路时如果只带 id 不带 knowledge_id**，同一个知识会被当成两条，双路分就合并不了！"

### Step 5：RRF 打分 + 累加（L476-L478）—— 双路命中在此实现

```python
rrf_score = 1.0 / (k + rank)             # 公式：名次越靠前，分越高
if item_id not in scores:                # 第一次见这个知识 → 新建账本
    scores[item_id] = {"rrf": 0.0, "vector_score": 0.0, "item": item}
scores[item_id]["rrf"] += rrf_score      # 再见到（另一路）→ 不新建，直接累加
```

**双路命中怎么实现的？—— 没有专门的判断代码！**

```
外层第1轮（向量路）碰到 12号：
  "12" 不在 scores？ → 在 → 不新建，直接累加
  → scores[12].rrf = 0 + 1/61 = 0.0164

外层第2轮（BM25路）又碰到 12号：
  "12" 不在 scores？ → 不在了 → 不新建，直接累加
  → scores[12].rrf = 0.0164 + 1/61 = 0.0328   ← 双路命中，翻倍！
```

机制 = **外层循环多跑一遍 + 同一个键被再次访问 + `if not in` 区分首/次**。

### Step 6：记展示分（L479-L484）

```python
if item.get("method") == "vector_search":   # 过滤器：只有向量路的条目才进来
    item_sim = item.get("score", 0)         # 取这条的相似度（0~1）
    if item_sim > scores[item_id]["vector_score"]:   # 保留见过的最高值
        scores[item_id]["vector_score"] = item_sim
```

**为什么必须有这个 `if`？**
- BM25 路的 score 是 5.2、3.1 这种加权分，展示给用户会懵（"5.2 是啥？"）
- 所以**展示分永远只记向量路的余弦相似度**（0~1），直观可读
- BM25 的条目到这里被 `if` 挡在外面，`vector_score` 不会被污染

**易混淆点**：这段不是"一次循环记两个东西"——一次迭代只处理"一路的一条"；向量路的条目才更新 vector_score，BM25 的条目直接跳过这块。

### Step 7：保留最佳详情（L485-L488）

```python
item_score = item.get("score", 0)                          # 这条的原始分
if item_score > scores[item_id]["item"].get("score", 0):   # 比已存的更高？
    scores[item_id]["item"] = item                         # 就替换成这条
```

**择优不是多存**：每个知识永远只有 1 个 `item`（内容模板）。

```
12号第一次（向量路）：score=0.82 → 存入 item（向量版）
12号第二次（BM25路）：score=5.2  → 5.2 > 0.82 → 替换成 BM25 版
最终 scores[12]["item"] = BM25 版（单路分最高的那份详情）
```

### Step 8：排序 + 截取（L490-L501）

```python
merged = sorted(scores.values(), key=lambda x: x["rrf"], reverse=True)  # 按累计RRF分从高到低
result = []
for entry in merged[:top_n]:            # 只取前 top_n 条（默认10）
    item = entry["item"].copy()         # 拿内容模板（浅拷贝，避免改到原数据）
    item["rrf_score"] = round(entry["rrf"], 4)   # 贴上排序分（调试用）
    item["score"] = round(entry["vector_score"], 4)  # 展示分统一覆盖成向量相似度
    item["rrf_only"] = entry["vector_score"] <= 0    # 标记：只有BM25命中、无语义匹配
    result.append(item)
```

### Step 9：防御性去重（L503-L514）

```python
seen = set()                          # 记录已放行的知识id
unique = []
for item in result:
    key = item.get("knowledge_id") or item.get("id")   # 再按 knowledge_id 认人
    if key is None or key in seen:    # 没id 或 已出现过 → 跳过
        continue
    seen.add(key)
    unique.append(item)
return unique
```

**为什么已有合并还要再清一遍？** 双保险。正常情况 Step 5 已按 knowledge_id 合并、不会重复；
万一未来新增某路用了不稳定 id 导致漏网，这里兜底再清一次，**确保返回的列表绝不含两条同一知识**。

---

## 六、完整示例走查（带账单变化过程）

### 数据准备

```python
result_sets = [
    # 向量路：2 条
    [{"id": "3f9a...", "knowledge_id": 12, "score": 0.82, "method": "vector_search", "title": "注塑机温度偏高"},
     {"id": "7b1e...", "knowledge_id": 33, "score": 0.61, "method": "vector_search", "title": "料筒温控失效"}],
    # BM25路：3 条
    [{"id": 12, "knowledge_id": 12, "score": 5.2, "method": "bm25_search", "title": "注塑机温度偏高"},
     {"id": 33, "knowledge_id": 33, "score": 3.1, "method": "bm25_search", "title": "料筒温控失效"},
     {"id": 45, "knowledge_id": 45, "score": 2.0, "method": "bm25_search", "title": "电机异响"}],
]
```

### 账单（scores）逐步变化

| 步骤 | 处理条目 | scores[12] | scores[33] | scores[45] |
|---|---|---|---|---|
| ① 向量路 12号 | 新建 | rrf=0.0164, vs=0.82 | —— | —— |
| ② 向量路 33号 | 新建 | 同上 | rrf=0.0161, vs=0.61 | —— |
| ③ BM25 12号 | 累加 | rrf=**0.0328**, vs 不变, item 换 BM25版 | —— | —— |
| ④ BM25 33号 | 累加 | —— | rrf=**0.0322**, item 换 BM25版 | —— |
| ⑤ BM25 45号 | 新建 | —— | —— | rrf=0.0159, vs=0, item=BM25版 |

（vs = vector_score）

### 最终输出

```
排序（按 rrf 降序）：12号(0.0328) > 33号(0.0322) > 45号(0.0159)

输出每条：
  12号 → rrf_score=0.0328, score=0.82, rrf_only=False
  33号 → rrf_score=0.0322, score=0.61, rrf_only=False
  45号 → rrf_score=0.0159, score=0.0,  rrf_only=True   ← BM25独中，会被下游过滤掉
```

---

## 七、几种边界情况

### 1. 知识只出现在一路

45号只在 BM25 路 → 只有 1/63 的分，`vector_score=0` → 标记 `rrf_only=True`。
下游（问答链路）会把 `rrf_only` 的过滤掉——**关键词对得上但语义没匹配上，不可信**。

### 2. 同一知识在两路名次不同

12号在向量路第 1、BM25 路第 5 → rrf = 1/61 + 1/65 = 0.0164 + 0.0154 = 0.0318。
虽然 BM25 路排得靠后，但两路都认 → 仍然明显高于单路第 1 的 0.0164。

### 3. 脏数据（无 id 无 knowledge_id）

`item_id = None` → Step 3 直接 `continue` 跳过，不会崩、不会污染账单。

### 4. 只有一路返回成功

`result_sets` 只传一路 → 外层只循环 1 次 → 等价于"单路按名次排序"，RRF 退化为普通排名。

### 5. 双库 id 撞号（手册库加入后的新边界）

知识 5 号和手册 5 号同时进入融合。若用 `knowledge_id` 当键：两者同键 → 被合并 → 其中一个（通常是后循环到的）被覆盖丢弃，**输出里只剩一个，且张冠李戴**。用 `_dedup_key`（`K:5` / `M:5`）则互不干扰，各自独立参与 RRF 计分。

### 6. 手册精确匹配只出现在一路（名次吃亏）

错误码精确匹配路（`method="manual_code_exact"`）的权威条目（score=1.0）只在 ③ 路出现，RRF 名次分天然低于"双路命中"的知识案例 → 融合后排不上去。**这不是 RRF 的 bug，是名次融合的固有倾向**——需要在下游按 `method == "manual_code_exact"` **置顶修正**（见十点五第 ③ 点）。

---

## 八、保留数量速查

| 层 | 保留条数 | 依据 | 说明 |
|---|---|---|---|
| scores 字典 | 每个知识 1 条 | `item_id` 作键 | 按 knowledge_id 去重合并 |
| RRF 输出 | top_n 条（默认 10） | `merged[:top_n]` | 参数可传，调用方决定 |
| 问答链路最终 | 最多 8 条 | `_filter_rerank_cases` 截前 8 | 阈值过滤 + 加权重排 + 设备/关键词严格过滤 |

> RRF 本身只"去重 + 排序 + 截取"，**不做相关度筛选**。真正的相关度过滤（score≥0.15 + 设备/故障关键词严格过滤）发生在融合之后。

---

## 九、常见疑问速查

| 疑问 | 答案 |
|---|---|
| 双路命中怎么判断的？ | 没有专门代码。外层循环第二轮碰到同键 → `if item_id not in scores` 区分首/次 → 累加 |
| 一次循环记了向量又记关键字？ | 不是。一次迭代只处理一路的一条；`vector_score` 用 `if method=="vector_search"` 过滤 |
| 每轮循环找到几条？ | 外层一轮 = 一路全部条目（多条）；内层一次 = 1 条（记账） |
| 每次循环算一条结果吗？ | 是"记账一条"，不是"产出结果一条"；结果在循环结束后统一排序产生 |
| 保留多少条？ | scores 每知识 1 条 → RRF 前 10 → 问答严格过滤后再筛到 8 |
| 知识库已去重为何还去重？ | 录入去重防"存重"；RRF 去重防"查重"（一次搜索两路各返回一份，合并成一条）|
| id / knowledge_id 啥关系？ | `knowledge_id`=数据库主键（身份证），`id`=两路各发各的（柜号），用 kid 合并 |
| method、"unknown" 是啥？ | `dict.get("method","unknown")` = 取来源路标签，取不到给默认值不报错 |
| 融合输入是筛选过的吗？ | 是两路各自召回 top_k 的候选集；相关度筛选在融合之后（score≥0.15） |
| rrf_only 是什么？ | 只有 BM25 命中、无语义匹配的标记，下游会过滤掉 |
| k=60 能改吗？ | 能，但一般不用改。k 越大名次间分差越小（越平滑）|

---

## 十、上下游（RRF 在整条链路中的位置）

```
用户提问
   ↓
① 两路召回（各自 top_k 条）
   ├─ vector_search（Milvus 语义） tools.py#L532
   └─ bm25_search（PG 关键词）     tools.py#L574
   ↓
② rrf_merge（本算法，去重+排序+截取） tools.py#L429
   ↓
③ 下游筛选（问答/专家模式共用 `_filter_rerank_cases`，search.py）
   ├─ 过滤 rrf_only + score≥0.15
   ├─ weighted_rerank 加权重排            tools.py#L322
   ├─ 严格过滤：设备类型精确匹配 + 故障关键词至少命中一个
   │    （剔除跨设备/泛相似案例；严格过滤为空 → 回退宽松 top2 防误伤）
   └─ 截前 8 条
   ↓
④ 喂给 LLM 生成回答（问答链路）
   └─ 专家模式额外：多故障时每路子查询各自走 ①②③，再按故障分组回答
```

调用示例（`/answer/stream` 中，`analyze_answer_stream`）：

```python
# ① 两路召回
vector_result = tools.vector_search(query=..., top_k=10, score_threshold=0.0)
bm25_result   = tools.bm25_search(query=..., top_k=10)
result_sets = [r.data for r in (vector_result, bm25_result) if r.success]

# ② RRF 融合
merged = rrf_merge(result_sets, top_n=10)

# ③ 下游筛选：统一走 _filter_rerank_cases（含严格过滤与空结果兜底）
device, kws = _extract_device_and_fault(tools, question)
filtered = _filter_rerank_cases(tools, merged, question,
                                require_device=device, require_keywords=tuple(kws))
#    内部 = 过滤 rrf_only + score≥0.15 → weighted_rerank 加权重排
#         → 设备精确匹配 + 故障关键词命中 → 空则回退宽松 top2 → 截前 8 条

# ④ 生成回答
for msg in answer_agent.stream_answer(question, filtered):
    yield msg
```

> 专家模式（`/answer/expert`）的每路子查询检索结果也走同一套 ①②③；区别仅在检索端用 `require_hybrid` 强制首轮 vector+BM25 双路（见 REACT_RETRIEVAL.md）。

---

## 十点五、双库四路融合（手册库加入后的完整形态）

> 公共编排层：`app/agents/retrieval_flow.py` 的 `retrieve_hybrid`（智能问答 / 专家 / 钉钉共用）

### ① 不是 4 个库，是 2 个库最多 4 路

```
                    ┌─ 知识库（knowledge） ① 向量检索（cos，Milvus）
                    │                      ② BM25 关键词检索
   问题 ── 提取错误码 ┤
  （含错误码才走③④）│ 手册库（log_code）  ③ 错误码精确匹配（查 PG 表，非向量）
                    │                      ④ 手册语义向量（Milvus）
                    └─ 全部路 → rrf_merge（按名次，最多 4 个 result_set）
```

普通问题（无错误码）：2 路进融合；报错误码（如 SV0436）：4 路进融合。

### ② 四路 RRF 累加示例（双库各自双路命中）

```
问题"机床报 SV0436 伺服过流"
知识案例《X轴过载报警》   ① 向量第1 + ② BM25第2 → 1/61 + 1/62        ← 知识库双路命中
手册条目《SV0436 过流》   ③ 精确第1 + ④ 向量第1 → 1/61 + 1/61 + 置顶  ← 手册库双路命中
```

同一条目四路全命中时 RRF 分最高可达 4 路累加；跨库条目由 `_dedup_key` 隔离各自计分。

### ③ 错误码精确匹配置顶修正（关键）

RRF 按名次融合后，③ 路的权威手册条目可能被知识库泛案例压下去 → 在 `filter_rerank_cases` 输出前按：

```python
sorted(key=lambda x: (0 if x.get("method") == "manual_code_exact" else 1, -x.get("score", 0)))
```

把 `manual_code_exact` 条目提到最前，其余按匹配度降序——**保证"错误码精确命中"永远排第一**，因为它是设备手册的权威标准处理，优先级高于知识库的相似案例。

### ④ 面试一句话总结（可背）

> "我的融合是 RRF 名次融合：2 个库最多 4 路（知识向量 / 知识BM25 / 手册错误码精确 / 手册向量），跨源分数不可比所以用名次；去重用复合键 `_dedup_key` 防两库自增 id 撞号；错误码精确命中在融合后置顶，保证手册权威答案不被知识库泛案例挤掉。"

---

## 十一、相关文件位置

| 内容 | 位置 |
|---|---|
| RRF 融合实现 | `backend/app/agents/tools.py#L429-L514` |
| 公共检索编排层（四路召回 + 融合 + 过滤） | `backend/app/agents/retrieval_flow.py` |
| 向量检索（召回） | `backend/app/agents/tools.py#L532` |
| BM25 检索（召回） | `backend/app/agents/tools.py#L574` |
| 加权重排（融合后） | `backend/app/agents/tools.py#L322` |
| 问答链路调用（融合→严格筛选→生成） | `backend/app/api/search.py#L241-L330`（`analyze_answer_stream`） |
| 严格过滤 + 加权重排（问答/专家共用） | `backend/app/api/search.py#L492`（`_filter_rerank_cases`） |
| 设备/故障关键词提取 | `backend/app/api/search.py#L471`（`_extract_device_and_fault`） |
| 专家模式（拆解 + 并行 ReAct） | `backend/app/api/search.py#L334`（`expert_answer_stream`） |
| Milvus 返回的 id/knowledge_id | `backend/app/core/vector_store.py#L246-L255` |
