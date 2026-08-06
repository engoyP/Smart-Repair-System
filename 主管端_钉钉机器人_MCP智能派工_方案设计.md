# 主管端 + 钉钉机器人 + MCP 智能派工 方案设计

> Status: 待审批
> Date: 2026-07-31
> 版本: v1.0（审批通过后进入执行）

***

## 0. 方案总览：你想要的场景长这样

```
【主管】在钉钉群里说（或主管端录入）:
  "车间2号注塑机，料筒温度异常，显示屏报错E-017，现场有焦味冒烟，紧急，优先派"
        ↓
【MCP服务 + DispatchAgent】
   1. 查今日值日排班：谁在岗（排除请假/下班）
   2. 查技能标签：谁擅长"注塑机/温度/PLC"
   3. 查当前负载：谁手上未完成工单最少
   4. 查距离定位：谁离车间2号最近（可选，暂不做）
   5. 综合打分 → 输出 Top3 推荐（含理由 + 置信度）
        ↓
【主管确认】（钉钉机器人卡片/主管端页面二选一）:
   > 推荐 1. 彭师傅 92 分（擅长注塑机温度，当前空闲，今日值日）
   > 推荐 2. 张师傅 73 分（通用维修，手上1台未完成）
   > 推荐 3. 王师傅 61 分（擅长电气，距离100m，相关度一般）
   主管选：彭师傅 → 确认派工
        ↓
【双向推送】
   ├─ Web 维修端（TechQueue.vue）：新工单 INBOX + 红点
   ├─ 钉钉卡片推送到彭师傅：
   │    "您有新维修任务 WO-20260731-008"
   │    【设备】车间2号注塑机 | 【优先级】紧急
   │    【故障】料筒温度异常 / E-017 / 冒烟
   │    按钮：[接受] [查看详情H5] [一键导航]
        ↓
【彭师傅操作 & 进度双向同步】（按钮/钉钉消息/Web端页面均可）
   彭师傅点击 [接受] → 进度 ACCEPTED
   到达现场点   [已到达] → 进度 ARRIVED
   开始检查点   [检查中] → 进度 INSPECTING
   修好后点     [完成]   → 进度 COMPLETED（填写维修报告+备件）
   ├─ 每次状态变更 → 钉钉机器人自动回推到主管群/主管单聊
   └─ 主管端「实时维修看板」→ 状态条滚动更新（带操作人 + 时间）
        ↓
【维修完成】
   知识库自动提取 / 审核 / 入库（现有逻辑复用）
   完成回执卡片推送给主管 + 创建人
   扣减备件库存（现有逻辑复用）
```

***

## 1. 技术栈选择（关键：为什么用 MCP + 不用 MCP 的部分）

| 模块                       | 方案                                        | 是否用 MCP     | 原因                                       |
| ------------------------ | ----------------------------------------- | ----------- | ---------------------------------------- |
| 主管端 Web UI               | Vue 3 + Element Plus，新页面                  | ❌ 不用        | 纯业务界面，没必要包一层 MCP                         |
| 钉钉机器人接收主管消息              | 钉钉 Stream 模式 Webhook / 后端接口               | ❌ 不用        | 钉钉官方 SDK 直接接                             |
| **AI 智能派工：查排班+技能+负载+打分** | **FastAPI 封装成标准 MCP Server**              | ✅ **用 MCP** | 后续可以直接接入 IDE AI/主管端 AI 机器人/对话式派工，不写第二套代码 |
| 维修进度双向同步                 | 后端状态机 + 钉钉工作通知 + Web 前端轮询/SSE             | ❌ 不用        | 状态机后端强管控更安全                              |
| 钉钉进度按钮回调                 | 钉钉互动卡片回传 → 后端 `/api/v1/dingtalk/callback` | ❌ 不用        | 钉钉原生互动卡片能力                               |
| 主管端页面内 AI 对话派工           | 通过 MCP 调用 dispatch\_tools                 | ✅ 用 MCP     | 一次定义工具，IDE/主管端都能用                        |

**为什么智能派工要用 MCP？**

* 未来你有 3 种派工入口：① 主管端手动填派单 ② IDE 里我（AI助手）帮你派 ③ 钉钉机器人 @AI 派工

* 不做 MCP：三种入口要各写一遍「查询排班+技能+负载+打分」逻辑 → 3 份代码维护

* 做 MCP：写 1 份 MCP 工具，3 个入口直接复用（MCP 设计目的就是这个）

***

## 2. 系统架构图

```
┌──────────────────────────────┐   ┌──────────────────────────────┐
│   主管入口（三选一）          │   │   维修员入口（三端同步）      │
│  ① 主管端Web派工中心         │   │  ① Web维修端（TechQueue）    │
│  ② 钉钉群/单聊 @机器人描述   │   │  ② 移动端H5 /m/queue         │
│  ③ 主管端 AI 对话框派工      │   │  ③ 钉钉卡片按钮              │
└──────────┬───────────────────┘   └──────────────┬───────────────┘
           │ 请求                                     │ 操作（接受/到达/完成）
           ▼                                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                    FastAPI 后端 (app.main:app)                    │
│                                                                   │
│  ┌───────────────┐  ┌───────────────┐  ┌──────────────────────┐  │
│  │ work_orders   │  │ users         │  │ 新增 work_order_     │  │
│  │ （现有）      │  │ （现有）      │  │ progress_logs 进度日志│  │
│  │ status 增强   │  │ skills 扩展   │  │ (状态机全轨迹)       │  │
│  │ 9种状态枚举   │  │ duty_schedule │  └──────────┬───────────┘  │
│  └───────┬───────┘  │ 排班表（新增）├─────────────┼──────────────┤
│          │          └───────┬───────┘             │              │
│          │ 派工评分         │技能/排班查询         │ 状态机流转   │
│          ▼                  ▼                     │              │
│   ┌─────────────────────────────────┐             │              │
│   │ 🧩 MCP Server (mcp_dispatch)    │             │              │
│   │  工具:                          │             │              │
│   │  • list_today_duty_techs        │             │              │
│   │  • get_tech_skills_and_load    │             │              │
│   │  • recommend_technician        │             │              │
│   │  • (可选) create_work_order    │             │              │
│   └─────────────────────────────────┘             ▼              │
│                                                     通知分发     │
│                                          ┌───────────────────┐   │
│                                          │  app/core/dingtalk│   │
│                                          │  （现有能力扩展） │   │
│                                          │• 派工互动卡片     │   │
│                                          │• 进度推送卡片     │   │
│                                          │• 完成回执卡片     │   │
│                                          └───────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

***

## 3. 数据库变更（新增/修改表）

### 3.1 工单状态机扩充（WorkOrderStatus）

> 现在只有 DRAFT / IN\_PROGRESS / COMPLETED，粒度太粗，无法显示你要的 6 步进度

| 新增值           | 含义                      | 触发动作                         | 通知谁                |
| ------------- | ----------------------- | ---------------------------- | ------------------ |
| `SUBMITTED`   | 主管已提交派工需求，AI推荐中         | 主管提交流程                       | -                  |
| `ASSIGNED`    | AI推荐完成，主管确认分派给某人，待维修员接受 | 主管确认派工 → **发钉钉+Web通知给维修员**   | 维修员（新任务）、主管（待接受回执） |
| `ACCEPTED`    | 维修员已接受任务，准备出发           | 钉钉/Web端点「接受」→ 回推主管           | 主管                 |
| `ARRIVED`     | 维修员已到达现场                | 点「已到达」 → 回推                  | 主管                 |
| `INSPECTING`  | 故障检查/诊断中                | 点「开始检查」 → 回推                 | 主管                 |
| `IN_PROGRESS` | 维修作业中（保留旧值）             | 开始执行维修 → 可跳过                 | 主管                 |
| `COMPLETED`   | 维修完成，已提交报告（保留旧值）        | 点「完成」填表单 → **回推主管+知识入库+扣库存** | 主管、创建人             |
| `REJECTED`    | 维修员/主管退回（新增）            | 退回需填写理由                      | 主管/创建人             |

迁移脚本：alembic 新增 `workorderstatus` enum 值（已支持 alter type add value）

### 3.2 新增：维修进度日志表 `work_order_progress_logs`

> 主管端看板展示全流程 + 审计追踪 + 耗时分析必备

| 字段              | 类型        | 说明                                                 |
| --------------- | --------- | -------------------------------------------------- |
| id              | PK        | -                                                  |
| work\_order\_id | FK        | 关联工单                                               |
| from\_status    | enum      | 原状态                                                |
| to\_status      | enum      | 新状态                                                |
| operator\_id    | FK        | 操作人（维修员/主管/系统）                                     |
| operator\_name  | string    | 冗余存姓名，查列表省 join                                    |
| source          | string    | 操作来源：`WEB` / `MOBILE` / `DINGTALK_CARD` / `SYSTEM` |
| remark          | text      | 操作理由/备注（如 REJECTED 理由、延迟原因）                        |
| location        | string    | 可选：到达现场定位坐标                                        |
| attachments     | JSONB     | 可选：到达现场照片/音频                                       |
| created\_at     | timestamp | 操作时间（自动）                                           |

用途：主管端每条工单点进去 → 完整时间轴（卡片展开）

### 3.3 新增：排班值日表 `duty_schedules`

> 派工第一步就是「今天谁值班」，主管可以排班（周循环/日指定/临时顶班）

| 字段             | 类型     | 说明                                          |
| -------------- | ------ | ------------------------------------------- |
| id             | PK     | -                                           |
| date           | DATE   | 值日日期（YYYY-MM-DD，建联合索引 date+shift）           |
| shift          | string | 早班/中班/晚班 `MORNING / AFTERNOON / NIGHT`      |
| user\_id       | FK     | 值日人员 ID（TECHNICIAN 角色）                      |
| schedule\_type | string | `WEEKLY_ROUTINE`（周排班自动生成） / `MANUAL`（主管手动改） |
| note           | string | 顶班/请假备注                                     |

初始化：第一次从周排班规则（主管设置）批量生成未来 30 天

### 3.4 扩展：users 技能字段升级

> 现有的 `skills` 是 string(500) 逗号分隔，做派工评分不够结构化

方案：**加列不删旧列，平滑迁移**

* 新增 `skills_json JSONB`：`{"机械": 5, "注塑机": 4, "液压": 3, "PLC电气": 5, "气动": 2}`（1-5 熟练度）

* 新增 `current_workload_count INTEGER DEFAULT 0`：当前未完成工单数（实时冗余，查询省 COUNT 子查询）

* 新增 `last_online_at TIMESTAMP`：最近操作时间，判断「谁还在岗」

旧 `skills string` 字段保留 1 个月后删，迁移脚本自动把逗号分隔转成 JSONB（默认熟练 3）

***

## 4. MCP Server 设计（唯一 MCP 部分）

### 4.1 文件位置

* 新增 `d:\WeiZhi Works\backend\mcp\dispatch_server.py`

* 安装依赖：`mcp`（官方标准库，轻量）+ 复用现有 `SessionLocal`/`DispatchAgent`

* 独立 uvicorn 进程启动（端口：默认 8001）

* TRAE 配置 `trae.json` / `.mcp.json` 里注册 `server_name: dispatch-mcp`，我就能直接调用

### 4.2 MCP 工具列表（4 个，足够覆盖派工场景）

| 工具名                     | 输入参数                                                                            | 返回内容                                                        | 什么时候用                                      |
| ----------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------ |
| `list_today_duty_techs` | date, shift(可选)                                                                 | 今日值日维修员列表：ID、姓名、工号、班次、是否在线                                  | 主管描述故障后，第一步先锁定今日能派的人（排除休班）                 |
| `get_tech_profile`      | user\_id                                                                        | 单个维修员画像：skills\_json 熟练度、当前工单数、近 30 天同类故障成功率、平均耗时           | 评分第二步拿详情                                   |
| `recommend_technician`  | fault\_description(必填), device\_id(可选), fault\_code(可选), priority(可选), date(可选) | **DispatchResult：Top3 推荐 + 每人评分拆解**（技能匹配/负载/距离/历史成功率）+ 推荐理由 | **核心工具**：主管输入描述，直接出推荐列表                    |
| `confirm_dispatch`      | work\_order\_id(或草稿信息), technician\_id, requester\_id(主管)                       | 创建正式工单或更新 technician\_id，状态=ASSIGNED，触发通知                   | 主管确认派工后执行（**这个工具是否放 MCP 待讨论**，建议放后端直接走，安全） |

### 4.3 MCP 复用现有 DispatchAgent 设计

> 好消息：你项目里已经有 `dispatch_agent.py` 做评分！MCP 层只是套壳 + 加排班过滤，不用重写评分

调用链：

```
MCP recommend_technician(description, device_id)
        ↓
1. list_today_duty_techs → 候选人池（过滤休班）
2. get_tech_profile 批量 → 技能+熟练度+负载
3. dispatch_agent.dispatch(wo, technicians) → 打分
        ├─ skill_match × 权重 0.5
        ├─ workload_score × 权重 0.2（手上工单越少越好）
        ├─ success_rate × 权重 0.2（同类历史成功率）
        └─ online_score × 权重 0.1（最近在线时间越近越好）
4. 输出 Top3 + 评分拆解 + 自然语言推荐理由
```

### 4.4 MCP 权限与安全

* 白名单端口绑定 `127.0.0.1:8001`，禁止公网暴露

* MCP 内部工具执行 DB 查询只读，`confirm_dispatch` 不放 MCP（放普通后端 API 走 JWT 更安全）

* 完整操作日志：`logs/mcp_dispatch.log`

***

## 5. 主管端 Web UI 新增/改造页面（4 个页面 + 1 个组件）

### 5.1 路由扩展（MainLayout 内，SUPERVISOR/ADMIN 角色可见）

```js
// router/index.js 新增 4 条
{ path: 'supervisor/dispatch',   component: SupervisorDispatch.vue,  meta: { title: '派工中心', roles: ['SUPERVISOR','ADMIN'] } }
{ path: 'supervisor/progress',   component: SupervisorProgress.vue,  meta: { title: '实时进度看板', roles: ['SUPERVISOR','ADMIN'] } }
{ path: 'supervisor/schedule',   component: SupervisorSchedule.vue,  meta: { title: '排班管理',   roles: ['SUPERVISOR','ADMIN'] } }
{ path: 'supervisor/dispatch-ai',component: SupervisorDispatchAI.vue,meta: { title: 'AI智能派工', roles: ['SUPERVISOR','ADMIN'] } }
```

MainLayout 侧边栏菜单按角色过滤：SUPERVISOR/ADMIN 才显示「主管中心」分组

### 5.2 页面1：派工中心 SupervisorDispatch.vue

主管手动录入派工信息的主表单（不用等 AI/机器人）

```
┌─────────────────────────────────────────────────────────┐
│ 📋 派工中心                          [AI智能推荐 按钮]  │
├─────────────────────────────────────────────────────────┤
│ 基本信息                                                   │
│   设备： [搜索选择+扫码]（必填）                           │
│   优先级： 紧急 ○ 高 ●中 ○ 低（默认中）                    │
│   故障码(已知)： [____]（可空，AI自动识别后续补）          │
│   故障现场描述：                                          │
│   ┌─────────────────────────────────────────┐            │
│   │注塑机料筒温度异常，显示屏报E-017，现场有焦味│            │
│   │冒烟，上一班次用的是PC+ABS料。图片上传(拖)│            │
│   └─────────────────────────────────────────┘            │
│   现场图片/语音： [选择文件] 拖拽区（最多10张/1分钟录音）   │
│                                                           │
│ ⭐ 智能推荐结果（点击 AI智能推荐 后渲染，实时轮询状态）      │
│   ┌── 推荐 1 彭师傅 ⭐92分 ⭐⭐⭐⭐⭐ 置信度高              │
│   │ 技能匹配：注塑机/温度/PLC 5★ 匹配                      │
│   │ 当前负载：0单 空闲                                    │
│   │ 历史同类：23单 成功率 95.6%  平均耗时 42 分钟         │
│   │ [✔ 选择他并派工]                                      │
│   ├── 推荐 2 张师傅 73分 ⭐⭐⭐⭐                           │
│   └── 推荐 3 王师傅 61分 ⭐⭐⭐                             │
│                                                           │
│ 手动选择（不认可推荐时兜底）：[下拉选维修员]               │
│ [取消]                [提交派工]（蓝色主按钮）             │
└─────────────────────────────────────────────────────────┘
```

### 5.3 页面2：实时进度看板 SupervisorProgress.vue

**你最关心的：主管看所有维修员实时进度**

核心布局：**三栏 + 状态时间轴**

* 上：今天的 KPI 卡片（待派工数 / 待接受数 / 进行中数 / 今日完成数 / 平均响应时长）

* 左：待办列表（SUBMITTED / ASSIGNED / ACCEPTED）

* 中：进行中列表 + 每单点击展开时间轴

* 右：维修员实时状态（谁在岗、手上几单、当前做什么、预计完成）

时间轴组件：

```
WO-20260731-008  注塑车间2号-料筒温度异常  🔴紧急  彭师傅
─────────────────────────────────────────────────────
🟢 10:02  主管陈  创建派工单  SUBMITTED
🟢 10:03  AI推荐  Top1彭师傅，主管确认派工 → ASSIGNED
🟢 10:04  彭师傅  钉钉卡片接受任务  → ACCEPTED（响应耗时2分钟）
🟢 10:11  彭师傅  [到达现场] 车间2号 → ARRIVED（到达耗时7分钟）
🟢 10:13  彭师傅  [开始检查] 温度传感器 → INSPECTING
⚪ ......
⏱ 耗时汇总：从派工→到达 7 分钟，总进行中 18 分钟...
[催办按钮：主管可发送钉钉提醒]  [改派：可换维修员]
```

### 5.4 页面3：排班管理 SupervisorSchedule.vue

* 周视图：周一\~周日 × 早中晚班 矩阵

* 每个单元格点选「添加值日人员」→ 多选维修员保存 → 自动批量生成 duty\_schedules

* 支持单天手动调整（请假/顶班标记）

* 一键「按本周模板复制到下月」批量生成

* 今日值日面板：实时高亮当前班次在岗人员

### 5.5 页面4：AI 智能派工对话框 SupervisorDispatchAI.vue

聊天窗口 UI + MCP 工具调用：

* 主管直接发：「2号注塑机料筒温度超，紧急，冒烟」

* AI 先调用 `recommend_technician` → 返回 Top3 → 渲染推荐卡片

* 主管点卡片「选1号派工」→ AI 确认后调后端 `POST /api/v1/work-orders/from-dispatch` 创建工单（状态=ASSIGNED，通知彭师傅）

* 全程对话可追溯（支持截图发群汇报）

> 注意：MCP 只负责 **推荐**，最终派工必须由后端 API 创建工单，保证权限/审计一致

***

## 6. 钉钉机器人与互动卡片改造

### 6.1 新能力列表（复用现有 dingtalk.py 扩展）

| 场景              | 钉钉消息形式                | 接收方      | 卡片按钮                                 |
| --------------- | --------------------- | -------- | ------------------------------------ |
| 主管提交派工单 → 通知维修员 | **互动卡片**（非纯文本）        | 被派的维修员单聊 | `[接受任务] [查看详情H5] [导航到现场] [10分钟后提醒我]` |
| 维修员接受任务 → 通知主管  | 互动卡片更新 + 普通消息         | 主管单聊/群   | `[查看进度H5]`                           |
| 维修员到达现场/开始检查/完成 | **卡片进度条回写**（同一张卡片更新）  | 主管 + 创建人 | 无需按钮，仅展示                             |
| 维修完成 → 回执主管     | 新完整卡片（含维修报告摘要/耗时/扣备件） | 主管 + 创建人 | `[打开系统Web看完整] [一键归档知识库]`             |
| 主管「催办」→ 提醒维修员   | 钉钉DING通知              | 维修员      | -                                    |
| 维修员「退回」→ 通知主管   | 卡片+退回理由输入框            | 主管       | `[重新派工]`                             |

### 6.2 钉钉互动卡片回传端点

**现有**：`/api/v1/dingtalk/callback`（扫码登录 OAuth 回调）

**新增**：在同一个 callback 路由里处理互动卡片回调回调（按 `EventType/CorpId` 分发）

* 事件类型 `cardActionCallback` → 识别按钮 payload（`action=accept&wo_id=8`）

* 执行 `work_orders.transition(8, "ACCEPTED", operator=彭师傅)` → 存 progress\_log

* → 通知主管 + 更新进度

### 6.3 钉钉 Stream 模式（可选，更稳定）

现有回调需要公网 URL（cpolar 内网穿透），如果 cpolar 不稳定：

* 改用钉钉 Stream 模式：后端建立 WebSocket 长连接，无需公网暴露

* SDK：`dingtalk-stream` 或自行封装，5 个事件 handler：`on_card_action / on_chat_receive / on_chat@mention`

***

## 7. 关键执行流程（5 条核心）

### 7.1 主管端→AI 推荐→派工→通知

```
S1 主管填表单/AI 输入故障 → POST /api/v1/dispatch/recommend
S2 后端 → MCP recommend_technician(desc,device_id) → MCP
S3 MCP 查排班 + 技能 + DispatchAgent 评分 → 返回 Top3
S4 主管选1 → POST /api/v1/work-orders/from-dispatch {draft, tech_id}
   → 创建工单，状态=ASSIGNED，technician_id=彭，created_by=主管
   → 插入 progress_log（SUBMITTED→ASSIGNED，操作人=主管）
S5 钉钉 dingtalk.send_interactive_card(tech_id, wo_card)
   → 彭师傅手机收到卡片
   → 同时 Web 维修端 TechQueue.vue：SSE 推送红点+新工单 INBOX
```

### 7.2 维修员钉钉卡片点接受→进度同步

```
S1 钉钉卡片 payload {action: accept, wo_id: 8} → /dingtalk/callback
S2 backend: work_orders.transition(8, 'ACCEPTED', operator=彭师傅)
   → progress_log(ASSIGNED → ACCEPTED, source=DINGTALK_CARD)
S3 通知主管：钉钉消息 + 主管端 Progress.vue SSE 推送（时间轴自动+1步）
S4 钉钉原卡片：按钮区替换为「✅ 已接受，预计 10:11 到达」
```

### 7.3 维修员到达现场→进度

**Web端 / 钉钉卡片 / 移动端** 三端按钮均可触发 → 统一走同一个状态机 API

```
POST /api/v1/work-orders/{id}/transition
    { to_status: 'ARRIVED', remark: '到达现场', attachments: [现场照.jpg], location: '...' }
→ 状态校验 + 存 log + 通知主管 + 钉钉卡片进度条更新(第二步✅)
```

### 7.4 维修完成→回执+扣库存+知识入库

全部复用现有 `POST /api/v1/work-orders/{id}/complete`，新增：

* 完成后 progress\_log 最后一步

* 发钉钉完成卡片给主管 + 创建人

* 主管端进度看板归档

### 7.5 主管退回工单/改派

* 退回：`POST /api/v1/work-orders/{id}/transition { to_status: 'REJECTED', remark: '...' }` → 通知原维修员

* 改派：`POST /api/v1/work-orders/{id}/reassign { new_tech_id }` → 状态 ASSIGNED，新维修员收卡片

***

## 8. 风险点和取舍

| 风险                       | 影响 | 规避方案                                               |
| ------------------------ | -- | -------------------------------------------------- |
| MCP Server 挂了 → AI 派工不能用 | 中  | 主管端随时可以手动下拉选维修员派工，MCP 只给推荐不阻塞业务                    |
| cpolar 内网穿透不稳定 → 钉钉回调失败  | 中  | ① 钉钉卡片 5 秒超时重试 3 次 ② 迁移到 Stream 模式（无需公网 URL）作为第二阶段 |
| 维修员不看钉钉/不接受              | 高  | ① 5 分钟未接受自动发钉钉 DING ② 10 分钟未接受自动通知主管人工介入+催办        |
| 派工评分不准                   | 低  | 前 2 周派工后主管手动改派数据训练：skills\_json 熟练度打分校准 + 权重 A/B 调 |
| 状态机并发（双端同时点接受）           | 中  | DB 行锁 + 乐观锁（版本号），重复调用幂等，log 只写 1 条                 |
| 安全：MCP 暴露公网              | 极高 | **强制 127.0.0.1**，写 confirm 类工具不放 MCP，只做只读推荐        |

***

## 9. 阶段实施计划（3 个阶段可独立交付）

### Phase 1：基础闭环（优先，主管端 + 状态机 + 进度日志 + 手动派工），约 2-3 天

✅ 交付内容：

1. 工单状态机 8 个枚举值 + Alembic 迁移
2. `work_order_progress_logs` 表 + 状态流转 API `/transition` + 幂等锁
3. 扩展 users 表：skills\_json / workload\_count / last\_online\_at
4. 主管端两页：派工中心（手动选择维修员）+ 实时进度看板 + 时间轴
5. 派工通知 + 进度通知：钉钉纯文本 + Web 前端轮询/SSE
6. 按钮：维修端 TechQueue/钉钉单聊 accept/arrive/inspect/complete

### Phase 2：AI 推荐 + 排班 + 钉钉互动卡片，约 3-4 天

✅ 交付内容：

1. `duty_schedules` 排班表 + 排班页面
2. 现有 DispatchAgent 扩展权重（排班过滤 + 负载 + 历史成功）
3. MCP Server（3 个只读工具）+ TRAE 注册
4. 派工中心 + AI 对话派工页集成推荐结果
5. 钉钉 5 种互动卡片 + callback 处理 + 卡片进度条回写
6. cpolar → Stream 模式升级（第二阶段可选）

### Phase 3：完善+优化，约 1-2 天

✅ 交付内容：

1. 退回/改派 + 催办通知 + 超时自动提醒
2. 定位到达 + 现场图片/语音上传
3. 主管端 KPI 卡片：响应时长/完成率/平均工时 + 数据驾驶舱集成
4. 性能：workload\_count 触发器自动刷新 / SSE 替代轮询

***

## 10. 需要你审批确认的 6 个决策点（✅/❌ 请回复）

请回复 A-F 每条的确认或修改意见，通过后我立即开始实施 Phase 1。

* **A. 工单状态机 8 步粒度**：`SUBMITTED→ASSIGNED→ACCEPTED→ARRIVED→INSPECTING→IN_PROGRESS→COMPLETED→REJECTED`，符合你现场流程吗？有没有漏状态或要合并的？

* **B. MCP 只做只读推荐**，「创建工单/确认派工」仍走后端 JWT API，这样安全边界是否接受？

* **C. 钉钉通知形式**：第一阶段先用纯文本工作通知，第二阶段再升互动卡片+进度条回写，接受吗？（互动卡片需要去钉钉开发者后台先配置互动卡片模板 ID）

* **D. 维修员触发进度的方式**：只做 Web 端+移动端按钮，钉钉卡片按钮第二阶段加，OK？

* **E. 新增 4 个主管端页面**（派工中心/实时进度/排班/AI对话派工），角色按 SUPERVISOR/ADMIN 过滤，你的主管是 `supervisor_chen`（现有 SUPERVISOR 角色），对吗？

* **F. 实施顺序**：Phase1（基础闭环）→ Phase2（AI+MCP+互动卡片）→ Phase3（优化），是否接受这个优先级？

> 等待你的审批回复 ✅ 或修改意见，收到后开写代码。

