# ============================================================
# Smart-Repair-System - 一键初始化脚本（Windows / PowerShell）
#
# 用法：
#   .\setup.ps1                    # 完整初始化（基础设施 + 后端 + 前端 + 数据库）
#   .\setup.ps1 -SkipInfra         # 跳过 Docker 基础设施
#   .\setup.ps1 -SkipBackend       # 跳过 Python 依赖安装
#   .\setup.ps1 -SkipFrontend      # 跳过前端 npm 安装
#   .\setup.ps1 -SkipDB            # 跳过数据库迁移与种子数据
# ============================================================

param(
    [switch]$SkipInfra,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$SkipDB
)

$ErrorActionPreference = "Continue"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$PipMirror = "https://pypi.tuna.tsinghua.edu.cn/simple"

function Step([string]$msg) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkCyan
}

function Ok([string]$msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Warn([string]$msg) {
    Write-Host "  [!] $msg" -ForegroundColor Yellow
}

function Fail([string]$msg) {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
}

Write-Host ""
Write-Host "Smart-Repair-System 一键初始化" -ForegroundColor White
Write-Host "项目目录: $RootDir" -ForegroundColor Gray

# ------------------------------------------------------------
# 0. 环境检查
# ------------------------------------------------------------
Step "0/6 环境检查"
$dockerOK = $false
try { docker --version | Out-Null; $dockerOK = $true } catch {}
if ($dockerOK) { Ok "Docker 已安装" } else { Warn "未检测到 Docker，请先安装 Docker Desktop" }

$pyVersion = ""
try { $pyVersion = (python --version 2>&1) } catch {}
if ($pyVersion) { Ok "Python: $pyVersion" } else { Warn "未检测到 Python，请先安装 Python 3.10+（勾选 Add to PATH）" }

$npmOK = $false
try { npm --version | Out-Null; $npmOK = $true } catch {}
if ($npmOK) { Ok "Node/npm 已安装" } else { Warn "未检测到 Node.js，请先安装（https://nodejs.org）" }

# ------------------------------------------------------------
# 1. Docker 基础设施
# ------------------------------------------------------------
if (-not $SkipInfra) {
    Step "1/6 启动 Docker 基础设施（PostgreSQL / Redis / Milvus / etcd / MinIO）"
    if ($dockerOK) {
        Set-Location $RootDir
        docker-compose up -d
        if ($LASTEXITCODE -eq 0) { Ok "容器已启动，等待健康检查..." } else { Fail "docker-compose up 失败" }
        Start-Sleep -Seconds 3
        docker-compose ps
    } else {
        Fail "跳过：Docker 不可用"
    }
} else {
    Write-Host "  跳过基础设施（-SkipInfra）" -ForegroundColor Gray
}

# ------------------------------------------------------------
# 2. 后端 Python 依赖
# ------------------------------------------------------------
if (-not $SkipBackend) {
    Step "2/6 后端 Python 依赖安装"
    if (-not (Test-Path $VenvPython)) {
        Write-Host "  创建虚拟环境 .venv ..."
        Set-Location $BackendDir
        python -m venv .venv
    } else {
        Ok "虚拟环境已存在"
    }
    if (Test-Path $VenvPython) {
        Write-Host "  安装依赖（清华镜像加速，含 torch 体积较大，请耐心等待）..."
        & $VenvPython -m pip install --upgrade pip -i $PipMirror | Out-Host
        & $VenvPython -m pip install -r (Join-Path $RootDir "requirements.txt") -i $PipMirror | Out-Host
        if ($LASTEXITCODE -eq 0) { Ok "Python 依赖安装完成" } else { Fail "依赖安装失败，请检查网络后重试" }
    } else {
        Fail "虚拟环境创建失败"
    }
} else {
    Write-Host "  跳过后端依赖（-SkipBackend）" -ForegroundColor Gray
}

# ------------------------------------------------------------
# 3. 环境变量 .env
# ------------------------------------------------------------
Step "3/6 环境配置检查"
$envFile = Join-Path $BackendDir ".env"
if (Test-Path $envFile) {
    Ok ".env 已存在"
} else {
    Copy-Item (Join-Path $BackendDir ".env.example") $envFile
    Warn "已从 .env.example 生成 .env，请编辑 backend\.env 填写："
    Warn "  - DEEPSEEK_API_KEY（AI 检索必填）"
    Warn "  - DINGTALK_*（钉钉集成，非必须可先不填）"
    Warn "  注意：默认模型为 Qwen3-Embedding-0.6B，首次使用会从国内镜像自动下载（约 1GB）"
}

# ------------------------------------------------------------
# 4. 数据库迁移 + 种子数据
# ------------------------------------------------------------
if (-not $SkipDB) {
    Step "4/6 数据库初始化（迁移 + 种子数据）"
    if (Test-Path $VenvPython) {
        Set-Location $BackendDir

        Write-Host "  执行 alembic 迁移 ..."
        & $VenvPython -m alembic upgrade head | Out-Host
        if ($LASTEXITCODE -eq 0) { Ok "数据库表结构就绪" } else { Fail "迁移失败，请确认 PostgreSQL 已启动且 .env 配置正确" }

        Write-Host "  导入种子数据 ..."
        foreach ($s in @("seed_knowledge", "seed_categories", "seed_fault_codes", "seed_data")) {
            Write-Host "    - $s.py"
            & $VenvPython (Join-Path $BackendDir "scripts\$s.py") | Out-Host
            if ($LASTEXITCODE -eq 0) { Ok "$s 完成" } else { Warn "$s 执行异常（可忽略或稍后手动重跑）" }
        }

        Write-Host "  同步知识向量到 Milvus（首次会下载 Embedding 模型，耗时较长）..."
        & $VenvPython (Join-Path $BackendDir "scripts\sync_vectors.py") | Out-Host
        if ($LASTEXITCODE -eq 0) { Ok "向量同步完成" } else { Warn "向量同步异常，请检查 Milvus 是否健康（docker-compose ps）" }
    } else {
        Fail "虚拟环境不存在，请先执行后端依赖安装"
    }
} else {
    Write-Host "  跳过数据库初始化（-SkipDB）" -ForegroundColor Gray
}

# ------------------------------------------------------------
# 5. 前端依赖
# ------------------------------------------------------------
if (-not $SkipFrontend) {
    Step "5/6 前端依赖安装"
    if ($npmOK) {
        Set-Location $FrontendDir
        if (-not (Test-Path "node_modules")) {
            npm install | Out-Host
        } else {
            Ok "node_modules 已存在，跳过安装"
        }
        if ($LASTEXITCODE -eq 0) { Ok "前端依赖就绪" } else { Fail "npm install 失败" }
    } else {
        Fail "跳过：npm 不可用"
    }
} else {
    Write-Host "  跳过前端依赖（-SkipFrontend）" -ForegroundColor Gray
}

# ------------------------------------------------------------
# 6. 完成
# ------------------------------------------------------------
Step "6/6 初始化完成，启动方式"
Set-Location $RootDir
Write-Host ""
Write-Host "  终端 1 - 基础设施（如已启动可跳过）:" -ForegroundColor Yellow
Write-Host "      docker-compose up -d"
Write-Host ""
Write-Host "  终端 2 - 后端:" -ForegroundColor Yellow
Write-Host "      cd backend"
Write-Host "      .\.venv\Scripts\Activate.ps1"
Write-Host "      uvicorn app.main:app --host 0.0.0.0 --port 18080"
Write-Host ""
Write-Host "  终端 3 - 前端:" -ForegroundColor Yellow
Write-Host "      cd frontend"
Write-Host "      npm run dev"
Write-Host ""
Write-Host "  访问: http://127.0.0.1:4173   接口文档: http://127.0.0.1:18080/docs" -ForegroundColor Green
Write-Host ""
