# ========================================
# Intelligent Assessment System - Start Script
# Usage: powershell -ExecutionPolicy Bypass -File .\start.ps1
# ========================================

$ErrorActionPreference = "Stop"
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
chcp.com 65001 | Out-Null
[Console]::InputEncoding = $utf8Encoding
[Console]::OutputEncoding = $utf8Encoding
$OutputEncoding = $utf8Encoding
$root = $PSScriptRoot
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# QA -> Admin 获取完整 LLM 密钥时使用的内部共享令牌.
# 未显式提供环境变量时，首次启动生成并保存在已被 .gitignore 忽略的 .runtime 中.
$runtimeDir = Join-Path $root ".runtime"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$internalTokenFile = Join-Path $runtimeDir "admin-internal-token"
$internalToken = [string]$env:ADMIN_INTERNAL_TOKEN
if ([string]::IsNullOrWhiteSpace($internalToken) -and (Test-Path -LiteralPath $internalTokenFile)) {
    $internalToken = [IO.File]::ReadAllText($internalTokenFile).Trim()
}
if ([string]::IsNullOrWhiteSpace($internalToken)) {
    $tokenBytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($tokenBytes)
    } finally {
        $rng.Dispose()
    }
    $internalToken = [Convert]::ToBase64String($tokenBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    [IO.File]::WriteAllText($internalTokenFile, $internalToken, $utf8Encoding)
}
$env:ADMIN_INTERNAL_TOKEN = $internalToken

$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}

$nodeRuntime = Get-ChildItem -LiteralPath (Join-Path $root ".runtime") -Directory -Filter "node-v*-win-x64" -ErrorAction SilentlyContinue |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "npm.cmd") } |
    Sort-Object Name -Descending |
    Select-Object -First 1
if (-not $nodeRuntime) {
    throw "Node.js environment is missing. Run .\setup.ps1 first."
}
$npmCmd = Join-Path $nodeRuntime.FullName "npm.cmd"
$env:Path = "$($nodeRuntime.FullName);$env:Path"

$java = Get-Command java -ErrorAction SilentlyContinue
if (-not $java) {
    throw "Java was not found in PATH. Install Java 17+ and rerun this script."
}

function Start-LoggedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $stdout = Join-Path $logDir "$Name.out.log"
    $stderr = Join-Path $logDir "$Name.err.log"
    Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden | Out-Null
}

function Test-ServicePort {
    param([Parameter(Mandatory = $true)][int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $asyncResult = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $asyncResult.AsyncWaitHandle.WaitOne(500, $false)) {
            return $false
        }
        $client.EndConnect($asyncResult)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting all services..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`n[1/4] Starting Python services (5)..." -ForegroundColor Yellow
$pyServices = @(
    @{Dir="python\knowledge-service";  Port=10252; Name="knowledge"},
    @{Dir="python\qa-service";         Port=10253; Name="qa"},
    @{Dir="python\indicator-service";  Port=10254; Name="indicator"},
    @{Dir="python\evaluation-service"; Port=10255; Name="evaluation"},
    @{Dir="python\ontology-service";   Port=10256; Name="ontology"}
)
foreach ($service in $pyServices) {
    if (Test-ServicePort -Port $service.Port) {
        Write-Host "  Already running: $($service.Name) (:$($service.Port))" -ForegroundColor DarkGreen
    } else {
        Start-LoggedProcess `
            -Name $service.Name `
            -FilePath $pythonExe `
            -Arguments @("-u", "main.py") `
            -WorkingDirectory (Join-Path $root $service.Dir)
        Write-Host "  Started $($service.Name) (:$($service.Port))" -ForegroundColor Green
    }
}

Write-Host "`n[2/4] Starting Java service..." -ForegroundColor Yellow
$adminJar = Join-Path $root "java\admin-service\target\admin-service-1.0.0.jar"
if (-not (Test-Path -LiteralPath $adminJar)) {
    $maven = Get-Command mvn -ErrorAction SilentlyContinue
    if (-not $maven) {
        throw "Admin JAR is missing and Maven was not found. Run .\setup.ps1 first."
    }
    Push-Location (Join-Path $root "java\admin-service")
    try {
        & $maven.Source package -DskipTests
    } finally {
        Pop-Location
    }
}
if (Test-ServicePort -Port 10258) {
    Write-Host "  Already running: admin (:10258)" -ForegroundColor DarkGreen
} else {
    Start-LoggedProcess `
        -Name "admin" `
        -FilePath $java.Source `
        -Arguments @(
            "-Dfile.encoding=UTF-8",
            "-Dsun.stdout.encoding=UTF-8",
            "-Dsun.stderr.encoding=UTF-8",
            "-jar",
            $adminJar,
            "--debug=false"
        ) `
        -WorkingDirectory $root
    Write-Host "  Started admin (10258)" -ForegroundColor Green
}

Write-Host "`n[3/4] Starting frontend..." -ForegroundColor Yellow
if (-not (Test-Path -LiteralPath (Join-Path $root "frontend\node_modules"))) {
    throw "Frontend dependencies are missing. Run .\setup.ps1 first."
}
if (Test-ServicePort -Port 10086) {
    Write-Host "  Already running: frontend (:10086)" -ForegroundColor DarkGreen
} else {
    Start-LoggedProcess `
        -Name "frontend" `
        -FilePath $npmCmd `
        -Arguments @("run", "dev", "--", "--host", "0.0.0.0") `
        -WorkingDirectory (Join-Path $root "frontend")
    Write-Host "  Started frontend (10086)" -ForegroundColor Green
}

Write-Host "`n[4/4] Waiting for startup..." -ForegroundColor Yellow
$allPorts = @(10086, 10252, 10253, 10254, 10255, 10256, 10258)
$allNames = @("Frontend", "Knowledge", "QA", "Indicator", "Evaluation", "Ontology", "Admin")
$startupTimeoutSeconds = 60
$deadline = (Get-Date).AddSeconds($startupTimeoutSeconds)

do {
    $pendingPorts = @($allPorts | Where-Object { -not (Test-ServicePort -Port $_) })
    if ($pendingPorts.Count -eq 0) { break }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Service Status" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$failed = @()
for ($i = 0; $i -lt $allPorts.Count; $i++) {
    $port = $allPorts[$i]
    $name = $allNames[$i]
    if (Test-ServicePort -Port $port) {
        Write-Host "  [OK] $name (:$port)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $name (:$port) - see logs\*.err.log" -ForegroundColor Red
        $failed += $name
    }
}

if ($failed.Count -gt 0) {
    throw "Some services failed to start: $($failed -join ', ')"
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Access: http://localhost:10086" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
