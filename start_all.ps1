# ============================================================
# start_all.ps1
# 一键启动：Docker 中间件 + 后端(18080) + 前端(4173)
# 用法：双击运行 或 右键「使用 PowerShell 运行」
#       首次运行会检查 Hyper-V 保留端口冲突，冲突时自动调用
#       fix_winnat_ports.ps1 提权修复（弹 UAC 确认一次）。
# ============================================================

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $Root 'backend'
$FrontendDir = Join-Path $Root 'frontend'
$FixScript   = Join-Path $Root 'fix_winnat_ports.ps1'
$BackendLog  = Join-Path $Root 'backend.log'
$BackendErr  = Join-Path $Root 'backend.err.log'
$FrontendLog = Join-Path $Root 'frontend.log'
$FrontendErr = Join-Path $Root 'frontend.err.log'

$projectPorts = 3000, 4173, 18080, 15432, 7379, 19530, 9091, 9000, 9001

function Get-ExcludedRanges {
    netsh interface ipv4 show excludedportrange protocol=tcp | ForEach-Object {
        if ($_ -match '^\s*(\d+)\s+(\d+)') {
            [PSCustomObject]@{ Start = [int]$Matches[1]; End = [int]$Matches[2] }
        }
    }
}
function Get-Conflicts($ranges) {
    @($projectPorts | Where-Object {
            $p = $_
            $ranges | Where-Object { $p -ge $_.Start -and $p -le $_.End }
        })
}

Write-Host ""
Write-Host "========== Smart-Repair-System 一键启动 ==========" -ForegroundColor Cyan

# ---- [0] 端口冲突检查与修复 ----
$ranges = Get-ExcludedRanges
$conflicts = Get-Conflicts $ranges
if ($conflicts.Count -gt 0) {
    Write-Host ("[!] 以下端口被 Hyper-V/WSL 保留段占用: {0}" -f ($conflicts -join ', ')) -ForegroundColor Yellow
    Write-Host "    将提权运行 fix_winnat_ports.ps1 修复（请在弹出的 UAC 窗口点「是」）..."
    try {
        Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$FixScript`"" -Wait
    } catch {
        Write-Host "提权启动失败（可能被拒绝），请手动以管理员身份运行 fix_winnat_ports.ps1" -ForegroundColor Red
        exit 1
    }
    # 重新检测
    $ranges = Get-ExcludedRanges
    $conflicts = Get-Conflicts $ranges
    if ($conflicts.Count -gt 0) {
        Write-Host ("[!] 修复后仍有冲突: {0}。请重启电脑后再运行本脚本。" -f ($conflicts -join ', ')) -ForegroundColor Red
        exit 1
    }
}
Write-Host "[OK] 端口检查通过，无冲突。" -ForegroundColor Green

# ---- [1/4] Docker 中间件 ----
Write-Host ""
Write-Host "[1/4] 启动 Docker 中间件（PG/Redis/Milvus/etcd/MinIO）..." -ForegroundColor Cyan
try {
    docker compose -f (Join-Path $Root 'docker-compose.dev.yml') up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose 执行失败" }
    Write-Host "    已拉起，等待健康检查（约 20 秒）..."
    Start-Sleep -Seconds 20
} catch {
    Write-Host "    Docker 启动失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    请确认 Docker Desktop 已启动后重新运行本脚本。" -ForegroundColor Yellow
    exit 1
}

# ---- [2/4] 后端 ----
Write-Host ""
Write-Host "[2/4] 启动后端 (http://localhost:18080) ..." -ForegroundColor Cyan
if (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "    后端已在运行，跳过。"
} else {
    Start-Process -FilePath 'python' `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '18080' `
        -WorkingDirectory $BackendDir -WindowStyle Hidden `
        -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendErr
    Write-Host ("    后端已启动（模型加载约需 1 分钟），日志: {0}" -f $BackendLog)
}

# ---- [3/4] Embedding 编码服务 ----
Write-Host ""
Write-Host "[3/4] 启动 Embedding 服务 (http://localhost:8010) ..." -ForegroundColor Cyan
if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "    Embedding 服务已在运行，跳过。"
} else {
    $env:CUDA_VISIBLE_DEVICES = ""  # CUDA 加载偶发崩溃，强制 CPU 保证稳定
    Start-Process -FilePath 'python' `
        -ArgumentList '-m', 'app.core.embedding_server', '--host', '0.0.0.0', '--port', '8010' `
        -WorkingDirectory $BackendDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $BackendDir 'logs\embedding_server.log') `
        -RedirectStandardError (Join-Path $BackendDir 'logs\embedding_server.err.log')
    Write-Host "    Embedding 服务已启动（模型加载约需 1-2 分钟）。"
}

# ---- [4/4] 前端 ----
Write-Host ""
Write-Host "[4/4] 启动前端 (http://localhost:4173) ..." -ForegroundColor Cyan
if (Get-NetTCPConnection -LocalPort 4173 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "    前端已在运行，跳过。"
} else {
    Start-Process -FilePath 'npm.cmd' `
        -ArgumentList 'run', 'dev' `
        -WorkingDirectory $FrontendDir -WindowStyle Hidden `
        -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErr
    Write-Host ("    前端已启动，日志: {0}" -f $FrontendLog)
}

Write-Host ""
Write-Host "================== 启动完成 ==================" -ForegroundColor Green
Write-Host "  前端  http://localhost:4173"
Write-Host "  后端  http://localhost:18080  (health: http://localhost:18080/health)"
Write-Host ""
Write-Host "提示：后端模型加载约需 1 分钟，期间接口不可用属正常现象。"
Read-Host "按回车键关闭本窗口（前后端进程不受影响）"
