# ========================================
# Intelligent Assessment System - Start Script
# Usage: .\start.ps1
# ========================================

$ErrorActionPreference = "Stop"
$root = "$PSScriptRoot"

# Must set PATH first so Start-Process inherits it
$nodeBin = "C:\Program Files\nodejs"
$javaHome = "$env:USERPROFILE\jdk17\jdk-17.0.14+7"
$javaBin = "$javaHome\bin"
$gitBin = "$env:USERPROFILE\git\cmd"
$env:Path = "$nodeBin;$javaBin;$gitBin;" + $env:Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting all services..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Python services
Write-Host "`n[1/4] Starting Python services (6)..." -ForegroundColor Yellow
$pyServices = @(
    @{Dir="python\knowledge-service";           Port=10252; Name="Knowledge"},
    @{Dir="python\qa-service";                  Port=10253; Name="QA"},
    @{Dir="python\indicator-service";           Port=10254; Name="Indicator"},
    @{Dir="python\evaluation-service";          Port=10255; Name="Evaluation"},
    @{Dir="python\ontology-service";            Port=10256; Name="Ontology"}
)
foreach ($svc in $pyServices) {
    Start-Process -FilePath python -ArgumentList "-u main.py" -WorkingDirectory "$root\$($svc.Dir)" -WindowStyle Hidden
    Write-Host "  Started $($svc.Name) (:$($svc.Port))" -ForegroundColor Green
}

# Java services
Write-Host "`n[2/4] Starting Java services (1)..." -ForegroundColor Yellow
$adminJar = "$root\java\admin-service\target\admin-service-1.0.0.jar"
if (-not (Test-Path $adminJar)) {
    Write-Host "  Building admin-service..." -ForegroundColor Yellow
    Push-Location "$root\java\admin-service"; mvn package -DskipTests -q; Pop-Location
}
Start-Process -FilePath "$javaBin\java.exe" -ArgumentList "-jar $adminJar" -WindowStyle Hidden
Write-Host "  Started Admin (10258)" -ForegroundColor Green

# Frontend
Write-Host "`n[3/4] Starting frontend..." -ForegroundColor Yellow
if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "  Installing dependencies..." -ForegroundColor Yellow
    Push-Location "$root\frontend"; npm install; Pop-Location
}
Start-Process -FilePath "$nodeBin\npx.cmd" -ArgumentList "vite --host" -WorkingDirectory "$root\frontend" -WindowStyle Hidden
Write-Host "  Started Frontend (10086)" -ForegroundColor Green

# Verify
Write-Host "`n[4/4] Waiting for startup..." -ForegroundColor Yellow
Start-Sleep 18

Write-Host "`n========================================" -ForegroundColor Cyan
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

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Access: http://localhost:10086" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan