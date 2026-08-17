# ============================================================
# start_embedding_server.ps1
# 启动本地统一推理服务（OpenAI 兼容，端口 8010）：
#   召回模型 bge-m3 + 精排模型 Qwen3-Reranker-0.6B
# 它是 RAGFlow 等外部系统与本系统检索链路的向量模型来源。
# 用法：右键「使用 PowerShell 运行」或  .\start_embedding_server.ps1
# ============================================================

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root 'backend'
$LogFile = Join-Path $BackendDir 'logs\embedding_server.log'
$ErrFile = Join-Path $BackendDir 'logs\embedding_server.err.log'
$HealthUrl = 'http://localhost:8010/health'

# Make sure the log directory exists
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null

Write-Host ""
Write-Host "========== 统一推理服务 (bge-m3 + Qwen3-Reranker-0.6B) ==========" -ForegroundColor Cyan

function Test-ServerReady {
    try {
        $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
        return $health.status -eq 'ok'
    } catch {
        return $false
    }
}

# Port conflict check
if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) {
    if (Test-ServerReady) {
        Write-Host "[OK] 推理服务已在运行且就绪。" -ForegroundColor Green
    } else {
        Write-Host "[!] 8010 端口被占用但 /health 未就绪，请检查日志: $LogFile" -ForegroundColor Yellow
    }
    exit 0
}

# Force CPU to avoid intermittent CUDA crashes during model load (see embeddings.py)
$env:CUDA_VISIBLE_DEVICES = ""

Write-Host "    正在启动推理服务 http://localhost:8010 ..." -ForegroundColor Cyan
Write-Host "    双模型（bge-m3 + Reranker）CPU 加载约需 3-6 分钟。日志: $LogFile"

Start-Process -FilePath 'python' `
    -ArgumentList '-m', 'app.core.embedding_server', '--host', '0.0.0.0', '--port', '8010' `
    -WorkingDirectory $BackendDir -WindowStyle Hidden `
    -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile

# 轮询 /health 直到双模型就绪（超时 300s）
$deadline = (Get-Date).AddSeconds(300)
$ready = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    if (Test-ServerReady) { $ready = $true; break }
}

if ($ready) {
    $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
    Write-Host ("[OK] 推理服务就绪: embedding={0} rerank={1} dim={2} (加载 {3}s)" -f `
        $health.embedding_model, $health.rerank_model, $health.dim, $health.load_secs) -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[!] 推理服务未在 300s 内就绪（模型加载失败或端口异常）。" -ForegroundColor Red
    Write-Host "    请检查日志: $LogFile / $ErrFile" -ForegroundColor Yellow
    exit 1
}
