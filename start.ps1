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
        # 仅保留项目内/相对路径兜底，机器特定的猜测路径（D:\app\qdrant 等）对其他同事无意义
        # 跨机器一致性统一依赖 QDRANT_HOME 环境变量或 PATH（安装步骤见 QUICKSTART.md）
        $qdrantCandidates = @(
            "$root\qdrant", "$root\..\qdrant"
        )
        foreach ($c in $qdrantCandidates) {
            if (Test-Path "$c\qdrant.exe") { $qdrantDir = $c; $qdrantExe = "$c\qdrant.exe"; break }
        }
    }
}
if (-not $qdrantExe) {
    # 未找到可执行文件时，先探测 :6333 端口：已在运行则不误报"向量检索不可用"
    $qdrantLive = netstat -ano | Select-String ":6333 " | Select-String "LISTENING"
    if ($qdrantLive) {
        Write-Host "[INFO] 未找到 qdrant.exe，但检测到 Qdrant 已在运行 (:6333)。设置 QDRANT_HOME 后可由脚本自动管理（安装步骤见 QUICKSTART.md）" -ForegroundColor Yellow
    } else {
        Write-Host "[WARN] Qdrant 未找到（请设置环境变量 QDRANT_HOME 指向 qdrant.exe 所在目录，或将其加入 PATH；安装步骤见 QUICKSTART.md），knowledge-service 向量检索将不可用" -ForegroundColor Yellow
    }
}

# MySQL：优先环境变量 MYSQL_HOME，其次 PATH，再次 Windows 服务（如 MySQL80）
# admin-service 依赖 MySQL；本机常以 Windows 服务方式运行，跨机器可设置 MYSQL_HOME 指向 MySQL 安装目录
$mysqlExe = $null
$mysqlDir = $null
$mysqlService = $null
if ($env:MYSQL_HOME -and (Test-Path "$env:MYSQL_HOME\bin\mysqld.exe")) {
    $mysqlDir = $env:MYSQL_HOME
    $mysqlExe = "$env:MYSQL_HOME\bin\mysqld.exe"
} else {
    try { $mysqlExe = (Get-Command mysqld -ErrorAction Stop).Source; $mysqlDir = Split-Path -Parent (Split-Path -Parent $mysqlExe) } catch {}
}
# Windows 服务方式兜底：检测 MySQL 服务（服务名以 MySQL 开头，如 MySQL80），Running/Stopped 均可识别，避免已运行服务被误报"未找到"
if (-not $mysqlExe) {
    $mysqlService = Get-Service | Where-Object { $_.Name -match '^MySQL' } | Select-Object -First 1
}
if (-not $mysqlExe -and -not $mysqlService) {
    Write-Host "[WARN] MySQL 未找到（可设置环境变量 MYSQL_HOME 指向 MySQL 安装目录，或确认已安装 MySQL 服务），admin-service 将无法连接数据库" -ForegroundColor Yellow
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

# MySQL（admin-service 依赖，需先启动）
Write-Host "" -NoNewline
Write-Host "[1/6] Starting MySQL..." -ForegroundColor Yellow
$mysqlRunning = netstat -ano | Select-String ":3306 " | Select-String "LISTENING"
if ($mysqlRunning) {
    Write-Host "  MySQL 已在运行 (:3306)，跳过启动" -ForegroundColor Green
} elseif ($mysqlService) {
    # 仅当服务处于已停止状态时才尝试启动；已运行但端口未监听属异常，单独提示
    if ($mysqlService.Status -eq 'Stopped') {
        try {
            Start-Service -Name $mysqlService.Name
            $mysqlWaited = 0
            while ($mysqlWaited -lt 15) {
                Start-Sleep -Seconds 1; $mysqlWaited++
                if (netstat -ano | Select-String ":3306 " | Select-String "LISTENING") { break }
            }
            if (netstat -ano | Select-String ":3306 " | Select-String "LISTENING") {
                Write-Host "  Started MySQL (:3306) <- 服务 $($mysqlService.Name)" -ForegroundColor Green
            } else {
                Write-Host "  [FAIL] MySQL 服务启动后 :3306 未监听" -ForegroundColor Red
            }
        } catch {
            Write-Host "  [FAIL] 启动 MySQL 服务 $($mysqlService.Name) 失败: $($_.Exception.Message)" -ForegroundColor Red
        }
    } else {
        Write-Host "  [WARN] MySQL 服务 $($mysqlService.Name) 状态为 $($mysqlService.Status)，但 :3306 未监听" -ForegroundColor Yellow
    }
} elseif ($mysqlExe) {
    Start-Process -FilePath $mysqlExe -WorkingDirectory $mysqlDir -WindowStyle Hidden
    $mysqlWaited = 0
    while ($mysqlWaited -lt 15) {
        Start-Sleep -Seconds 1; $mysqlWaited++
        if (netstat -ano | Select-String ":3306 " | Select-String "LISTENING") { break }
    }
    if (netstat -ano | Select-String ":3306 " | Select-String "LISTENING") {
        Write-Host "  Started MySQL (:3306) <- $mysqlDir" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] MySQL 启动后 :3306 未监听" -ForegroundColor Red
    }
} else {
    Write-Host "  [SKIP] MySQL 未安装" -ForegroundColor Yellow
}

# Qdrant（knowledge-service 依赖，需先启动）
Write-Host "" -NoNewline
Write-Host "[2/6] Starting Qdrant..." -ForegroundColor Yellow
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
    $qdrantRunning = netstat -ano | Select-String ":6333 " | Select-String "LISTENING"
    if ($qdrantRunning) {
        Write-Host "  Qdrant 已在运行 (:6333)，跳过启动" -ForegroundColor Green
    } else {
        Write-Host "  [SKIP] Qdrant 未安装（未找到 qdrant.exe 且 :6333 未监听）" -ForegroundColor Yellow
    }
}

# Python services
Write-Host "" -NoNewline
Write-Host "[3/6] Starting Python services (5)..." -ForegroundColor Yellow
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
Write-Host "[4/6] Starting Java services (1)..." -ForegroundColor Yellow
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
        # admin-service 的 Spring profile 与 LOG_ENV 对齐（logback-spring.xml 用 dev/prod 切换日志策略）
        # 未设 LOG_ENV 时默认 dev，避免落到 default profile（仅控制台、无文件日志、非 JSON）
        $env:SPRING_PROFILES_ACTIVE = $env:LOG_ENV
        if (-not $env:SPRING_PROFILES_ACTIVE) { $env:SPRING_PROFILES_ACTIVE = "dev" }
        Start-Process -FilePath $javaExe -ArgumentList "-jar `"$adminJar`"" -WorkingDirectory "$root" -WindowStyle Hidden
        Write-Host "  Started Admin (10258)" -ForegroundColor Green
    } else {
        Write-Host "  [SKIP] Admin jar not found (Maven 编译可能失败)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [SKIP] Java / Maven 未安装" -ForegroundColor Yellow
}

# Frontend
Write-Host "" -NoNewline
Write-Host "[5/6] Starting frontend..." -ForegroundColor Yellow
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

# Verify — 按端口轮询等待，避免固定等待导致慢启动服务误报
Write-Host "" -NoNewline
Write-Host "[6/6] Waiting for startup..." -ForegroundColor Yellow

$allPorts = @(3306, 6333, 10086, 10252, 10253, 10254, 10255, 10256, 10258)
$allNames = @("MySQL","Qdrant","Frontend","Knowledge","QA","Indicator","Evaluation","Ontology","Admin")

# 状态：$null=未检查, $true=就绪, $false=超时
$status = @{}
foreach ($n in $allNames) { $status[$n] = $null }

$maxWait = 60  # 每个端口最长等待秒数
$elapsed = 0
while ($elapsed -lt $maxWait) {
    for ($i = 0; $i -lt $allPorts.Count; $i++) {
        $n = $allNames[$i]
        # 已确定状态的端口不再重复检查
        if ($null -ne $status[$n]) { continue }
        $p = $allPorts[$i]
        $ok = netstat -ano | Select-String ":$p " | Select-String "LISTENING"
        if ($ok) {
            $status[$n] = $true
        }
    }
    # 全部就绪 → 提前退出
    $allReady = $true
    foreach ($n in $allNames) { if (-not $status[$n]) { $allReady = $false; break } }
    if ($allReady) { break }
    Start-Sleep -Seconds 1
    $elapsed++
}

# 仍未就绪的标记为超时
foreach ($n in $allNames) {
    if ($null -eq $status[$n]) { $status[$n] = $false }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Service Status" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

for ($i = 0; $i -lt $allPorts.Count; $i++) {
    $p = $allPorts[$i]
    $n = $allNames[$i]
    if ($status[$n]) {
        Write-Host "  [OK] $n (:$p)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $n (:$p)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Access: http://localhost:10086" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
