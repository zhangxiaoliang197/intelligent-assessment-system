# ============================================================
# 自举引导：强制使用 PowerShell 7+（pwsh）运行本脚本。
# 若由 Windows PowerShell 5.1（或更低）启动，自动用 pwsh 重启自身。
# ============================================================
if ($PSVersionTable.PSVersion.Major -lt 7) {
    $pwshPath = $null
    $pwshCmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($pwshCmd) { $pwshPath = $pwshCmd.Source }
    if (-not $pwshPath) {
        foreach ($c in @("$env:ProgramFiles\PowerShell\7\pwsh.exe", "${env:ProgramFiles(x86)}\PowerShell\7\pwsh.exe")) {
            if ($c -and (Test-Path $c)) { $pwshPath = $c; break }
        }
    }
    if ($pwshPath) {
        & $pwshPath -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath @args
        exit $LASTEXITCODE
    }
    Write-Host "[ERROR] 本脚本需要 PowerShell 7+ (pwsh)，但未检测到。请安装 PowerShell 7 后重试。" -ForegroundColor Red
    exit 1
}

# ========================================
# Intelligent Assessment System - Stop Script
# Usage: .\stop.ps1
# ========================================

$ErrorActionPreference = "Continue"
$root = "$PSScriptRoot"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Stopping all services..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 注意：GeoServer (:9090) 故意不在此列表 —— 它是仓库外的常驻外部服务，由 start.ps1 按
# ensure-up 语义管理（已在运行就跳过，从不强杀）。如需停止请用其 Jetty STOP 端口 8079
# （-DSTOP.KEY=geoserver）或 bin\shutdown.bat。
$ports = @(10086, 10252, 10253, 10254, 10255, 10256, 10257, 10258)
$names = @("Frontend","Knowledge","QA","Indicator","Evaluation","Ontology","Situation","Admin")

# ── 第 1 步：按端口杀进程树 ──
$stopped = 0
Write-Host "`n[1/3] Killing processes by port..." -ForegroundColor Yellow
for ($i = 0; $i -lt $ports.Count; $i++) {
    $port = $ports[$i]
    $name = $names[$i]
    $ids = (netstat -ano | Select-String ":$port " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique)
    if ($ids) {
        foreach ($id in $ids) {
            # PowerShell 原生杀进程，加 taskkill /T 确保子进程也被杀
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 300
            taskkill.exe /F /PID $id /T 2>$null
        }
        Write-Host "  [OK] Stopped $name (:$port)" -ForegroundColor Green
        $stopped++
    } else {
        Write-Host "  [--] $name (:$port) - Not running" -ForegroundColor DarkGray
    }
}

# ── 第 2 步：按进程名杀残留 python/node ──
Write-Host "`n[2/3] Killing Python/Node processes..." -ForegroundColor Yellow
$procNames = @("python", "node")
foreach ($pn in $procNames) {
    $procs = Get-Process -Name $pn -ErrorAction SilentlyContinue
    if ($procs) {
        foreach ($p in $procs) {
            try {
                $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($p.Id)" -ErrorAction SilentlyContinue).CommandLine -as [string]
                # 只杀项目相关的 python/node 进程
                if ($cmd -match "uvicorn|vite|npx|knowledge-service|qa-service|indicator-service|evaluation-service|ontology-service|situation-service|frontend") {
                    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Milliseconds 200
                    taskkill.exe /F /PID $p.Id /T 2>$null
                }
            } catch { }
        }
    }
}

# ── 第 3 步：确认端口已释放 ──
Write-Host "`n[3/3] Verifying ports..." -ForegroundColor Yellow
Start-Sleep 2
$stillRunning = @()
foreach ($port in $ports) {
    $ids = (netstat -ano | Select-String ":$port " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] })
    if ($ids) {
        $stillRunning += $port
    }
}
if ($stillRunning) {
    Write-Host "  [WARN] Ports still in use: $($stillRunning -join ', ')" -ForegroundColor Yellow
} else {
    Write-Host "  All tracked ports released (GeoServer :9090 为外部常驻服务，不在此范围内)." -ForegroundColor Green
}

Write-Host ""
Write-Host "Total stopped: $stopped services" -ForegroundColor White
