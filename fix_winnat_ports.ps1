# ============================================================
# fix_winnat_ports.ps1
# 彻底解决 Hyper-V/WSL 动态保留端口冲突
# 原理：Hyper-V/WSL 每次启动会随机保留一段端口（如 2644-3243），
#       被圈走的端口任何程序都无法监听。本项目端口（3000/4173/18080/
#       15432/7379/19530/9091/9000/9001）随时可能被圈走。
#       本脚本把 WinNAT 动态端口范围固定到 50000-64999，保留段就
#       永久固定在高位，项目端口再也不受影响。
# 用法：右键「使用 PowerShell 运行」（会自动弹 UAC 提权）
#       或管理员 PowerShell 执行： .\fix_winnat_ports.ps1
# 注意：执行后建议重启一次电脑使其永久生效。
# ============================================================

# 自动检测是否管理员，不是则重新以管理员身份运行
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "正在请求管理员权限..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$ErrorActionPreference = 'SilentlyContinue'
$TargetStart = 50000   # 动态端口范围起点
$TargetCount  = 15000  # 端口数量（50000-64999）

Write-Host ""
Write-Host "================= 修复前保留端口范围 =================" -ForegroundColor Cyan
netsh interface ipv4 show excludedportrange protocol=tcp

# ---- 1. 固定所有 NAT 网关的动态端口范围 ----
Write-Host ""
Write-Host "[1/3] 固定 WinNAT 动态端口范围 -> $TargetStart-$($TargetStart + $TargetCount - 1) ..." -ForegroundColor Cyan
$natUpdated = $false
try {
    $nats = Get-NetNat
    if ($nats) {
        foreach ($n in $nats) {
            Write-Host ("  NAT: {0}  原动态端口: {1}-{2}" -f $n.Name, $n.DynamicPortRangeStartPort,
                ($n.DynamicPortRangeStartPort + $n.DynamicPortRangeNumberOfPorts - 1)) -ForegroundColor Gray
            Set-NetNat -Name $n.Name -DynamicPortRangeStartPort $TargetStart -DynamicPortRangeNumberOfPorts $TargetCount
            $natUpdated = $true
        }
    } else {
        Write-Host "  未发现 NAT 网关（将由 winnat 重启自动分配）" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Set-NetNat 执行异常: $($_.Exception.Message)" -ForegroundColor Yellow
}

# ---- 2. 重启 winnat 使保留段按新范围重新分配 ----
Write-Host ""
Write-Host "[2/3] 重启 winnat 服务（Docker/WSL 网络会短暂中断，稍后自动恢复）..." -ForegroundColor Cyan
Stop-Service winnat -Force
Start-Sleep -Seconds 3
Start-Service winnat
Start-Sleep -Seconds 5

# ---- 3. 验证 ----
Write-Host ""
Write-Host "================= 修复后保留端口范围 =================" -ForegroundColor Cyan
netsh interface ipv4 show excludedportrange protocol=tcp

$projectPorts = 3000, 4173, 18080, 15432, 7379, 19530, 9091, 9000, 9001
$ranges = netsh interface ipv4 show excludedportrange protocol=tcp | ForEach-Object {
    if ($_ -match '^\s*(\d+)\s+(\d+)') {
        [PSCustomObject]@{ Start = [int]$Matches[1]; End = [int]$Matches[2] }
    }
}
$conflicts = @($projectPorts | Where-Object {
        $p = $_
        $ranges | Where-Object { $p -ge $_.Start -and $p -le $_.End }
    })

Write-Host ""
Write-Host "================= 项目端口安全性检查 =================" -ForegroundColor Cyan
$projectPorts | ForEach-Object {
    $p = $_
    $hit = $ranges | Where-Object { $p -ge $_.Start -and $p -le $_.End }
    if ($hit) {
        Write-Host ("  {0,-6} [X] 被保留段 {1}-{2} 圈走" -f $p, $hit.Start, $hit.End) -ForegroundColor Red
    } else {
        Write-Host ("  {0,-6} [OK] 安全" -f $p) -ForegroundColor Green
    }
}

if ($conflicts.Count -gt 0) {
    Write-Host ""
    Write-Host "仍有端口冲突: $($conflicts -join ', ')。建议重启电脑后再运行本脚本一次。" -ForegroundColor Yellow
    Write-Host "若反复无法修复，可关闭 Docker Desktop 后重试（Docker 会重新创建 NAT）。"
} else {
    Write-Host ""
    Write-Host "[OK] 所有项目端口均已脱离保留段！重启电脑后永久生效，此后一键启动脚本将不再报警。" -ForegroundColor Green
}
Write-Host ""
