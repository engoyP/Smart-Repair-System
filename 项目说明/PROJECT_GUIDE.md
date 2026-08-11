# Smart-Repair-System — 操作指南

> **项目简介**：面向制造企业的设备维修数字化平台，覆盖工单全流程、设备台账、备件库存、排班与维修知识库。核心亮点：
> ① **RAG 混合检索**——Milvus 语义向量 + PostgreSQL BM25 关键词双路召回，RRF 融合后按故障原因加权重排，用大白话描述故障即可命中历史案例；
> ② **多 Agent 协作**——意图路由、ReAct 检索循环、回答/追踪维修/派工 Agent，支持自然语言排查引导；
> ③ **钉钉深度集成**——扫码绑定、机器人对话、OA 审批、工单卡片推送；
> ④ **技术栈** Vue3 + FastAPI + LangGraph，Milvus 向量库支撑语义检索。

> 本文档覆盖：Docker 常用指令、前后端启动、Git 初始化与常用指令
> 环境：Windows 10/11 + PowerShell

---

## 一、项目结构速览

```
d:\Smart-Repair-System
├── docker-compose.yml      # 基础设施编排（PostgreSQL / Redis / Milvus / etcd / MinIO）
├── requirements.txt        # Python 依赖清单（唯一权威版本）
├── backend/                # FastAPI 后端（Python 3.x）
│   ├── app/                # 业务代码（api / agents / core / models）
│   ├── alembic/            # 数据库迁移
│   ├── scripts/            # 种子数据脚本（seed_*.py）
│   ├── .env                # 环境配置（勿提交到 Git）
│   ├── .env.example        # 配置模板（可提交）
│   └── start_backend.ps1   # 一键启动后端
├── frontend/               # Vue3 + Vite 前端
│   └── package.json        # 前端依赖（npm）
└── RETRIEVAL_PIPELINE.md   # 检索机制详解文档
```

| 服务 | 容器/进程 | 本机端口 | 说明 |
|---|---|---|---|
| PostgreSQL | maintenance_postgres | 15432 | 关系数据（用户/工单/知识元数据） |
| Redis | maintenance_redis | **7379** | 缓存 + 会话（注意不是 6379） |
| Milvus | maintenance_milvus | 19530 / 9091 | 向量库（语义检索） |
| etcd | maintenance_etcd | 2379 | Milvus 元数据 |
| MinIO | maintenance_minio | 9000 / 9001 | 对象存储（Milvus 依赖） |
| 后端 API | uvicorn（本机进程） | 18080 | FastAPI（注意：8000 曾多次被 Hyper-V/WSL 保留段占用，已统一迁移到 18080） |
| 前端 | vite（本机进程） | 4173 | 开发服务器，代理 /api → 18080（3000 也曾被保留段占用，见 五、常见问题） |

---

## 二、Docker 常用指令

### 2.1 查看与状态

```powershell
docker --version                 # 查看 Docker 版本
docker-compose --version         # 查看编排工具版本
docker-compose ps                # 查看当前项目所有容器状态（关键排查命令）
docker ps                        # 查看运行中的容器
docker ps -a                     # 查看所有容器（含已停止）
docker images                    # 查看本地镜像
```

> 排查提示：Milvus 连接不上时，**先执行 `docker-compose ps`** 确认 5 个容器是否都 Up 且 healthy，这是最常见的坑。

### 2.2 启动 / 停止

```powershell
# 启动全部基础设施（postgres/redis/etcd/minio/milvus），-d 表示后台运行
docker-compose up -d

# 只启动某个服务（依赖会自动先启动）
docker-compose up -d postgres redis
docker-compose up -d milvus

# 重新构建并启动（改了 docker-compose.yml 后执行）
docker-compose up -d --build

# 停止全部容器（容器仍在，数据卷保留，重启数据不丢）
docker-compose down

# 停止并删除所有容器 + 网络（数据卷仍保留）
docker-compose down -v          # ⚠️ 慎用！-v 会连数据卷一起删，数据库数据全丢
```

### 2.3 查看日志

```powershell
docker-compose logs -f              # 跟踪所有服务日志
docker-compose logs -f milvus       # 只看某个服务
docker-compose logs --tail=100 postgres   # 只看最后 100 行
```

### 2.4 进入容器操作

```powershell
# 进入 PostgreSQL 容器（交互式）
docker exec -it maintenance_postgres bash
# 然后可在容器内执行 psql：
#   psql -U admin -d maintenance_db

# 或一行直接执行 SQL（不进入容器）
docker exec -it maintenance_postgres psql -U admin -d maintenance_db -c "SELECT count(*) FROM knowledge_items;"

# 进入 Redis 容器执行命令
docker exec -it maintenance_redis redis-cli ping        # 返回 PONG 说明正常
docker exec -it maintenance_redis redis-cli KEYS "*"    # 查看所有 key

# 进入 Milvus 容器
docker exec -it maintenance_milvus bash
```

### 2.5 清理

```powershell
docker system df                 # 查看磁盘占用
docker system prune              # 清理无用镜像/容器/网络（不影响数据卷）
docker rm 容器名                  # 删除指定容器
docker rmi 镜像ID                # 删除指定镜像
```

---

## 三、项目启动（完整流程）

### 3.1 首次初始化（只做一次）

```powershell
# ① 启动基础设施
cd "d:\Smart-Repair-System"
docker-compose up -d
docker-compose ps                # 确认 5 个容器都 Up

# ② 准备后端虚拟环境（已在项目里建过 .venv 的跳过）
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1       # 激活虚拟环境（PowerShell）
pip install -r ..\requirements.txt  # 安装依赖（清单在项目根目录）

# ③ 环境配置：把 backend\.env.example 复制一份为 backend\.env
#    并填入你的 DeepSeek / 钉钉等真实密钥（当前项目已有 .env，此步可跳过）

# ④ 初始化数据库表结构（alembic 迁移）
cd "d:\Smart-Repair-System\backend"
alembic upgrade head

# ⑤ 导入种子数据（顺序执行）
python scripts\seed_knowledge.py      # 必跑：导入 200 条维修知识案例
python scripts\seed_categories.py     # 故障分类
python scripts\seed_fault_codes.py    # 故障编码
python scripts\seed_data.py           # 基础数据（用户/设备/备件等）

# ⑥ 把知识条目向量同步到 Milvus（语义检索依赖）
python sync_vectors.py
# 预期输出：✅ 向量同步完成！ 成功: N

# ⑦ 启动后端（端口 18080，见下方"端口冲突修复"）
# 方式 A（推荐，脚本里已带正确参数）：
powershell -ExecutionPolicy Bypass -File start_backend.ps1
# 方式 B（等价手写命令）：
uvicorn app.main:app --host 0.0.0.0 --port 18080

# ⑧ 另开一个终端启动前端（端口 4173）
cd "d:\Smart-Repair-System\frontend"
npm install          # 首次安装依赖（node_modules）
npm run dev          # 启动开发服务器（端口在 vite.config.js 里配置为 4173）
```

> ⚠️ **端口说明（重要）**：本项目后端统一用 **18080**、前端 **4173**。
> 原来的 8000 / 3000 多次被 **Hyper-V/WSL 动态保留端口段**圈走（每次开机随机分配一段端口，被圈走的端口任何程序都绑不上，报 `WinError 10013`），所以已全部迁移。若再遇到端口被占/绑定失败，见 **五、常见问题排查 → 端口冲突**。

### 3.2 日常启动（正常使用）

**推荐方式：一键启动脚本**（自动检查端口冲突 → 拉起 Docker → 启动前后端）：

```powershell
# ① 先打开 Docker Desktop
# ② 双击 / 运行项目根目录的一键启动脚本
cd "d:\Smart-Repair-System"
.\start_all.ps1
```

脚本会自动完成：端口体检（冲突时弹 UAC 自动调用 fix_winnat_ports.ps1 修复）→ `docker compose up -d` → 后台启动后端(18080) + 前端(4173)，日志写在项目根目录 `backend.log` / `frontend.log`。

**手动方式（等价）：**

```powershell
# 终端 1：启动基础设施
cd "d:\Smart-Repair-System"
docker compose up -d

# 终端 2：启动后端
cd "d:\Smart-Repair-System\backend"
uvicorn app.main:app --host 0.0.0.0 --port 18080

# 终端 3：启动前端
cd "d:\Smart-Repair-System\frontend"
npm run dev
```

浏览器访问：
- 前端页面：http://127.0.0.1:4173
- 后端接口文档（Swagger）：http://127.0.0.1:18080/docs
- 健康检查：http://127.0.0.1:18080/api/v1/health

### 3.3 常用维护操作

```powershell
# 新增/修改了数据库模型后，生成并执行迁移
cd "d:\Smart-Repair-System\backend"
alembic revision --autogenerate -m "描述本次改动"
alembic upgrade head

# 知识库里新增了知识条目，需要重新同步向量（增量）
python sync_vectors.py

# 查看后端实时日志（uvicorn 终端里 Ctrl+C 停止）
# 日志文件：backend/logs/app.log
```

---

## 四、Git 常用指令

### 4.1 概念速记

```
工作区（你的代码） → git add → 暂存区 → git commit → 本地仓库 → git push → 远程仓库(GitHub)
                                                    ← git pull ←
```

### 4.2 首次创建仓库并上传（本项目已做，步骤保留参考）

```powershell
cd "d:\Smart-Repair-System"

# ① 初始化仓库
git init

# ② 添加所有文件到暂存区
git add -A                      # 或按需 git add 具体文件/目录

# ③ 查看暂存内容，确认没有 .env 等敏感文件（.gitignore 已自动排除）
git status

# ④ 提交
git commit -m "init: Smart-Repair-System 初始提交"

# ⑤ 关联远程仓库（GitHub 上先建好同名仓库）
git remote add origin https://github.com/你的用户名/Smart-Repair-System.git

# ⑥ 推送（-u 记住远程，以后直接 git push）
git push -u origin master
```

> 🌐 **国内网络 GitHub 推送失败（443 超时）的解决办法**：
> 若本地开了 Clash 等代理（端口常见 7897），先设置代理再推送：
> ```powershell
> $env:HTTPS_PROXY="http://127.0.0.1:7897"
> $env:HTTP_PROXY="http://127.0.0.1:7897"
> git push -u origin master
> ```

### 4.3 日常使用

```powershell
git status                      # 查看工作区状态（谁改了什么）
git diff                        # 查看未暂存的改动内容
git diff --staged               # 查看已暂存的改动

git add 文件名                   # 暂存单个文件
git add .                       # 暂存当前目录所有改动
git add -A                      # 暂存所有改动（含删除）

git commit -m "说明文字"         # 提交
git commit --amend -m "新说明"   # 修改上一次提交的信息

git log --oneline -5            # 查看最近 5 次提交
git log --oneline --graph       # 图形化查看分支历史

git push                        # 推送到远程（首次需 -u origin 分支名）
git pull                        # 拉取远程最新代码（= fetch + merge）
git fetch                       # 只下载远程更新，不合并

git branch                      # 查看本地分支
git branch -a                   # 查看所有分支（含远程）
git branch 新分支名              # 创建分支
git checkout 分支名              # 切换分支
git checkout -b 新分支名         # 创建并切换
git merge 分支名                # 把指定分支合并到当前分支
git branch -d 分支名             # 删除已合并的分支
```

> **commit 消息建议（可选规范）**：用 `类型: 描述` 格式更专业，GitHub 提交历史一目了然：
>
> | 前缀 | 含义 | 例子 |
> |---|---|---|
> | `feat:` | 新功能 | `feat: 新增一键初始化脚本 setup.ps1` |
> | `fix:` | 修复 bug | `fix: 修复 RRF 合并去重错误` |
> | `docs:` | 文档改动 | `docs: 补充操作指南` |
> | `refactor:` | 重构（行为不变） | `refactor: 重写查询清洗逻辑` |
> | `chore:` | 构建/配置等杂务 | `chore: 更新依赖版本` |

### 4.4 撤销与回滚

```powershell
git restore 文件名               # 丢弃工作区改动，还原到最近一次提交
git restore --staged 文件名      # 把已暂存的文件移出暂存区（不丢改动）
git reset HEAD~1                # 撤销最近一次提交（保留改动）
git reset --hard HEAD~1         # 撤销最近一次提交并丢弃改动（⚠️ 不可找回）
git checkout -- 文件名           # 老版本写法，同 git restore
```

### 4.5 分支协作建议流程（多人开发）

```powershell
# 自己干活前先拉最新
git pull

# 从主干拉出自己的功能分支
git checkout -b feature/xxx

# ... 开发、提交若干次 ...

# 切回主干并合并
git checkout master
git merge feature/xxx

# 推送到远程
git push

# 删掉用过的分支
git branch -d feature/xxx
```

### 4.6 安全红线（务必遵守）

| 事项 | 说明 |
|---|---|
| **.env 不能提交** | 含 DeepSeek / 钉钉 / 阿里云密钥，已加进 .gitignore |
| 不要 `git push --force` | 会覆盖远程历史，除非你明确知道后果 |
| 不要提交 `.venv/`、`node_modules/` | 体积大且可重建，已被 .gitignore 排除 |
| commit 前先 `git status` | 检查是否有敏感文件混入 |

### 4.7 提交与推送实战

**① 查看暂存区（缓存区）**

```powershell
git status                    # 哪些文件已暂存 / 未暂存
git diff --cached --stat      # 暂存区改动摘要（文件级别）
git diff --cached             # 暂存区完整改动内容
git diff                      # 未暂存的改动内容
```

**② 提交指定文件 / 所有文件**

```powershell
# 只提交指定文件：先把不提交的移出暂存区，再提交剩余文件
git restore --staged <文件>
git commit -m "说明"

# 或全部取消暂存后，再精确暂存要提交的
git restore --staged .
git add backend/app/main.py
git commit -m "只提交 main.py"

# 提交所有改动（含新增文件）
git add .
git commit -m "说明"
```

> 注意：`git commit -am "说明"` 只能提交**已跟踪**文件的修改，新增文件必须先 `git add`。

**③ 查看修改与提交记录**

```powershell
git status                   # 当前未提交的修改
git log --oneline            # 简洁提交历史
git log --stat -5            # 最近 5 次提交改了哪些文件
git show <提交ID> --stat      # 某次提交改了哪些文件
```

**④ 推送被拒（fetch first）处理**

远程有新提交、本地没有时，`git push` 会报 `! [rejected] (fetch first)`。这是 git 的保护机制——它只接受接在**远程最新提交**后面的历史，防止顶掉别人/其他机器的提交。解决办法：**先拉取、再推送**。

```powershell
git pull --rebase origin master   # ① 先拉取远程更新（rebase 历史更整洁）
git push origin master            # ② 再推送
```

- 不想用 rebase 也可用 `git pull origin master`（会多产生一个合并提交）
- 若出现冲突（conflict）提示，先解决冲突再继续，不要硬操作

---

## 五、常见问题排查速查表

| 现象 | 排查步骤 |
|---|---|
| 后端启动报数据库连接失败 | `docker compose ps` 看 postgres 是否 healthy；`docker compose logs postgres` |
| Milvus 连接失败 | 同上，先看 `docker compose ps`；再 `docker exec -it maintenance_milvus bash` 确认进程 |
| Redis 连不上 | 检查 .env 里 REDIS_PORT=**7379**（compose 映射 7379→容器内 6379） |
| 前端接口 404 / 502 | 确认后端 **18080** 已启动；确认 vite 代理指向 127.0.0.1:18080 |
| **端口绑定失败 `WinError 10013`（端口被 Hyper-V/WSL 保留段圈走）** | 运行 `netsh interface ipv4 show excludedportrange protocol=tcp` 看端口是否在保留段内；然后右键管理员运行 `.\fix_winnat_ports.ps1` 把 WinNAT 动态端口固定到 50000+（一劳永逸），或直接运行 `.\start_all.ps1` 自动修复 |
| GitHub push 超时 | 设置 Clash 代理后重试（见 4.2） |
| 改了代码不生效 | 后端确认已重启；前端 vite 热更新需页面刷新 |
| 数据库表结构对不上 | `alembic upgrade head` 执行最新迁移 |
| 检索不到新知识 | 新增知识后执行 `python sync_vectors.py` 同步向量 |
| 钉钉扫码 404 | 电脑重启后 cpolar 域名会变，需同步更新 `backend/.env` 的 `DINGTALK_REDIRECT_URI` / `SERVER_PUBLIC_URL` 和钉钉后台「登录回调地址」（cpolar 转发目标固定为 localhost:18080） |
