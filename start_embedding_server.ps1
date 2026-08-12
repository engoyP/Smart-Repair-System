# ============================================================
# start_embedding_server.ps1
# Start the local Embedding service (OpenAI-compatible, port 8010).
# It serves as the vector model source for RAGFlow and other systems.
# Usage: right-click "Run with PowerShell" or  .\start_embedding_server.ps1
# ============================================================

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root 'backend'
$LogFile = Join-Path $BackendDir 'logs\embedding_server.log'
$ErrFile = Join-Path $BackendDir 'logs\embedding_server.err.log'

# Make sure the log directory exists
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null

Write-Host ""
Write-Host "========== Embedding Server ==========" -ForegroundColor Cyan

# Port conflict check
if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "    Port 8010 is already in use. Embedding service may already be running." -ForegroundColor Yellow
    exit 0
}

# Force CPU to avoid intermittent CUDA crashes during model load (see embeddings.py)
$env:CUDA_VISIBLE_DEVICES = ""

Write-Host "    Starting Embedding service at http://localhost:8010 ..." -ForegroundColor Cyan
Write-Host "    Model load takes about 1-2 minutes. Log: $LogFile"

Start-Process -FilePath 'python' `
    -ArgumentList '-m', 'app.core.embedding_server', '--host', '0.0.0.0', '--port', '8010' `
    -WorkingDirectory $BackendDir -WindowStyle Hidden `
    -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile

Start-Sleep -Seconds 3
Write-Host "[OK] Started in background. Health check: http://localhost:8010/health" -ForegroundColor Green
Write-Host ""
Write-Host "Note: first model load is slow, the endpoint may be temporarily unavailable." -ForegroundColor Yellow
