# ========================================
# Intelligent Assessment System - Start Script
# Usage: .\start.ps1
# ========================================

$ErrorActionPreference = "Continue"
$root = "$PSScriptRoot"

# ── 工具路径检测（从 PATH / 常见安装位置自动查找）──

# Node.js：从 PATH 查找
$nodeBin = $null
try { $nodeBin = Split-Path -Parent (Get-Command node -ErrorAction Stop).Source } catch {}
if (-not $nodeBin) {
    Write-Host "[WARN] Node.js 未在 PATH 中找到，前端将跳过" -ForegroundColor Yellow
}

# Java：从 PATH 查找，反推 JAVA_HOME
$javaExe = $null
$javaBin = $null
try {
    $javaExe = (Get-Command java -ErrorAction Stop).Source
    $javaBin = Split-Path -Parent $javaExe          # e.g. D:\dev\jdk17\bin
    $env:JAVA_HOME = Split-Path -Parent $javaBin     # 向上两级: D:\dev\jdk17
} catch {
    Write-Host "[WARN] Java 未在 PATH 中找到，admin-service 将跳过" -ForegroundColor Yellow
}

# Maven：从 PATH 查找，反推 Maven Home
$mvnHome = $null
$mvnCmd = $null
try {
    $mvnCmd = (Get-Command mvn.cmd -ErrorAction Stop).Source
    $mvnHome = Split-Path -Parent (Split-Path -Parent $mvnCmd)  # bin → Maven Home
} catch {
    Write-Host "[WARN] Maven 未在 PATH 中找到，admin-service 将跳过编译" -ForegroundColor Yellow
}

# Qdrant：优先环境变量 QDRANT_HOME，其次 PATH，再次常见安装位置
# 同事机器安装位置可能不同，按此顺序查找以保证通用性
$qdrantExe = $null
$qdrantDir = $null
if ($env:QDRANT_HOME -and (Test-Path "$env:QDRANT_HOME\qdrant.exe")) {
    $qdrantDir = $env:QDRANT_HOME
    $qdrantExe = "$env:QDRANT_HOME\qdrant.exe"
} else {
    try { $qdrantExe = (Get-Command qdrant -ErrorAction Stop).Source; $qdrantDir = Split-Path -Parent $qdrantExe } catch {}
    if (-not $qdrantExe) {
        $qdrantCandidates = @(
            "D:\app\qdrant", "D:\qdrant", "C:\qdrant", "C:\Program Files\qdrant",
            "$root\qdrant", "$root\..\qdrant"
        )
        foreach ($c in $qdrantCandidates) {
            if (Test-Path "$c\qdrant.exe") { $qdrantDir = $c; $qdrantExe = "$c\qdrant.exe"; break }
        }
    }
}
if (-not $qdrantExe) {
    Write-Host "[WARN] Qdrant 未找到（可设置环境变量 QDRANT_HOME 指向 qdrant.exe 所在目录），knowledge-service 向量检索将不可用" -ForegroundColor Yellow
}

# 将工具加入 PATH，确保子进程可继承
$paths = @($nodeBin, $javaBin)
if ($mvnHome) { $paths += "$mvnHome\bin" }
$extraPath = ($paths | Where-Object { $_ }) -join ";"
if ($extraPath) {
    $env:Path = "$extraPath;$env:Path"
}

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

# Qdrant（knowledge-service 依赖，需先启动）
Write-Host "" -NoNewline
Write-Host "[1/5] Starting Qdrant..." -ForegroundColor Yellow
if ($qdrantExe) {
    $qdrantRunning = netstat -ano | Select-String ":6333 " | Select-String "LISTENING"
    if ($qdrantRunning) {
        Write-Host "  Qdrant 已在运行 (:6333)，跳过启动" -ForegroundColor Green
    } else {
        Start-Process -FilePath $qdrantExe -WorkingDirectory $qdrantDir -WindowStyle Hidden
        $qdrantWaited = 0
        while ($qdrantWaited -lt 15) {
            Start-Sleep -Seconds 1; $qdrantWaited++
            if (netstat -ano | Select-String ":6333 " | Select-String "LISTENING") { break }
        }
        if (netstat -ano | Select-String ":6333 " | Select-String "LISTENING") {
            Write-Host "  Started Qdrant (:6333) <- $qdrantDir" -ForegroundColor Green
        } else {
            Write-Host "  [FAIL] Qdrant 启动后 :6333 未监听" -ForegroundColor Red
        }
    }
} else {
    Write-Host "  [SKIP] Qdrant 未安装" -ForegroundColor Yellow
}

# Python services
Write-Host "" -NoNewline
Write-Host "[2/5] Starting Python services (5)..." -ForegroundColor Yellow
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
Write-Host "[3/5] Starting Java services (1)..." -ForegroundColor Yellow
$adminJar = "$root\java\admin-service\target\admin-service-1.0.0.jar"
if ($mvnCmd -and $javaExe) {
    if (-not (Test-Path $adminJar)) {
        Write-Host "  Building admin-service..." -ForegroundColor Yellow
        Push-Location "$root\java\admin-service"
        & "$mvnCmd" package -DskipTests -q
        Pop-Location
    }
    if (Test-Path $adminJar) {
        Kill-Port 10258
        Start-Process -FilePath $javaExe -ArgumentList "-jar $adminJar" -WindowStyle Hidden
        Write-Host "  Started Admin (10258)" -ForegroundColor Green
    } else {
        Write-Host "  [SKIP] Admin jar not found (Maven 编译可能失败)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [SKIP] Java / Maven 未安装" -ForegroundColor Yellow
}

# Frontend
Write-Host "" -NoNewline
Write-Host "[4/5] Starting frontend..." -ForegroundColor Yellow
if ($nodeBin) {
    if (-not (Test-Path "$root\frontend\node_modules")) {
        Write-Host "  Installing dependencies..." -ForegroundColor Yellow
        Push-Location "$root\frontend"; npm install; Pop-Location
    }
    Kill-Port 10086
    Start-Process -FilePath "$nodeBin\npx.cmd" -ArgumentList "vite --host" -WorkingDirectory "$root\frontend" -WindowStyle Hidden
    Write-Host "  Started Frontend (10086)" -ForegroundColor Green
} else {
    Write-Host "  [SKIP] Node.js 未安装" -ForegroundColor Yellow
}

# Verify
Write-Host "" -NoNewline
Write-Host "[5/5] Waiting for startup..." -ForegroundColor Yellow
Start-Sleep 18

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Service Status" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$allPorts = @(6333, 10086, 10252, 10253, 10254, 10255, 10256, 10258)
$allNames = @("Qdrant","Frontend","Knowledge","QA","Indicator","Evaluation","Ontology","Admin")
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
