# ========================================
# Intelligent Assessment System - Start Script
# Usage: .\start.ps1
# ========================================

$ErrorActionPreference = "Continue"
$root = "$PSScriptRoot"

# Must set PATH first so Start-Process inherits it
$nodeBin = Split-Path -Parent (Get-Command node -ErrorAction Stop).Source
$javaExe = (Get-Command java -ErrorAction Stop).Source
$javaBin = Split-Path -Parent $javaExe
$mvnHome = "$env:USERPROFILE\apache-maven\apache-maven-3.9.8"
$mvnCmd = "$mvnHome\bin\mvn.cmd"
$env:Path = "$nodeBin;$javaBin;$mvnHome\bin;$env:Path"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting all services..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ── 通用端口清理函数 ──
function Kill-Port($port) {
    $ids = (netstat -ano | Select-String ":$port " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique)
    if ($ids) {
        foreach ($id in $ids) {
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 300
            taskkill.exe /F /PID $id /T 2>$null
        }
        Start-Sleep 1
    }
}

# Python services
Write-Host "" -NoNewline
Write-Host "[1/4] Starting Python services (5)..." -ForegroundColor Yellow
$env:ADMIN_SERVICE_URL = "http://localhost:10258"
$pyServices = @(
    @{Dir="python\knowledge-service";           Port=10252; Name="Knowledge"},
    @{Dir="python\qa-service";                  Port=10253; Name="QA"},
    @{Dir="python\indicator-service";           Port=10254; Name="Indicator"},
    @{Dir="python\evaluation-service";          Port=10255; Name="Evaluation"},
    @{Dir="python\ontology-service";            Port=10256; Name="Ontology"}
)
foreach ($svc in $pyServices) {
    Kill-Port $svc.Port
    Start-Process -FilePath python -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port $($svc.Port)" -WorkingDirectory "$root\$($svc.Dir)" -WindowStyle Hidden
    Write-Host "  Started $($svc.Name) (:$($svc.Port))" -ForegroundColor Green
}

# Java services
Write-Host "" -NoNewline
Write-Host "[2/4] Starting Java services (1)..." -ForegroundColor Yellow
$adminJar = "$root\java\admin-service\target\admin-service-1.0.0.jar"
Write-Host "  Building admin-service..." -ForegroundColor Yellow
Push-Location "$root\java\admin-service"
$env:JAVA_HOME = "C:\Program Files\Java\jdk-17"
& "$mvnCmd" package -DskipTests -q
Pop-Location
if (Test-Path $adminJar) {
    Kill-Port 10258
    Start-Process -FilePath $javaExe -ArgumentList "-jar $adminJar" -WindowStyle Hidden
    Write-Host "  Started Admin (10258)" -ForegroundColor Green
} else {
    Write-Host "  [SKIP] Admin jar not found" -ForegroundColor Yellow
}

# Frontend
Write-Host "" -NoNewline
Write-Host "[3/4] Starting frontend..." -ForegroundColor Yellow
if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "  Installing dependencies..." -ForegroundColor Yellow
    Push-Location "$root\frontend"; npm install; Pop-Location
}
Kill-Port 10086
Start-Process -FilePath "$nodeBin\npx.cmd" -ArgumentList "vite --host" -WorkingDirectory "$root\frontend" -WindowStyle Hidden
Write-Host "  Started Frontend (10086)" -ForegroundColor Green

# Verify
Write-Host "" -NoNewline
Write-Host "[4/4] Waiting for startup..." -ForegroundColor Yellow
Start-Sleep 18

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Service Status" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$allPorts = @(10086, 10252, 10253, 10254, 10255, 10256, 10258)
$allNames = @("Frontend","Knowledge","QA","Indicator","Evaluation","Ontology","Admin")
for ($i = 0; $i -lt $allPorts.Count; $i++) {
    $p = $allPorts[$i]
    $n = $allNames[$i]
    $ok = netstat -ano | Select-String ":$p " | Select-String "LISTENING"
    if ($ok) {
        Write-Host "  [OK] $n (:$p)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $n (:$p)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Access: http://localhost:10086" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
