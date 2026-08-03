# ========================================
# Intelligent Assessment System - Stop Script
# Usage: .\stop.ps1
# ========================================

$ErrorActionPreference = "Continue"
$root = "$PSScriptRoot"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Stopping all services..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$ports = @(10086, 10252, 10253, 10254, 10255, 10256, 10258)
$names = @("Frontend","Knowledge","QA","Indicator","Evaluation","Ontology","Admin")

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
                if ($cmd -match "uvicorn|vite|npx|knowledge-service|qa-service|indicator-service|evaluation-service|ontology-service|frontend") {
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
    Write-Host "  All ports released." -ForegroundColor Green
}

Write-Host ""
Write-Host "Total stopped: $stopped services" -ForegroundColor White
