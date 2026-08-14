# ============================================================
# 智能评估系统 - MySQL 一键初始化脚本
# 用法：.\init-mysql.ps1
#       或 .\init-mysql.ps1 -Host 192.168.1.100 -User root -Password mypass
# ============================================================

param(
    [string]$HostName = $(if ($env:MYSQL_HOST) { $env:MYSQL_HOST } else { "localhost" }),
    [string]$Port     = $(if ($env:MYSQL_PORT) { $env:MYSQL_PORT } else { "3306" }),
    [string]$User     = $(if ($env:MYSQL_USER) { $env:MYSQL_USER } else { "root" }),
    [string]$Password = $(if ($env:MYSQL_PASSWORD) { $env:MYSQL_PASSWORD } else { "" }),
    [string]$Database = $(if ($env:MYSQL_DATABASE) { $env:MYSQL_DATABASE } else { "assessment" }),
    [switch]$SkipConfirm
)

# ============================================================
# 自举引导：强制使用 PowerShell 7+（pwsh）运行本脚本。
# 若由 Windows PowerShell 5.1（或更低）启动，自动用 pwsh 重启自身（含参数透传）。
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
        $relaunchArgs = @()
        foreach ($entry in $PSBoundParameters.GetEnumerator()) {
            if ($entry.Value -is [System.Management.Automation.SwitchParameter]) {
                if ($entry.Value) { $relaunchArgs += "-$($entry.Key)" }
            } else {
                $relaunchArgs += "-$($entry.Key)"
                $relaunchArgs += [string]$entry.Value
            }
        }
        & $pwshPath -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath @relaunchArgs
        exit $LASTEXITCODE
    }
    Write-Host "[ERROR] 本脚本需要 PowerShell 7+ (pwsh)，但未检测到。请安装 PowerShell 7 后重试。" -ForegroundColor Red
    exit 1
}

$ErrorActionPreference = "Stop"
$root = "$PSScriptRoot"
$sqlFile = "$root\init-mysql.sql"

if (-not (Test-Path $sqlFile)) {
    Write-Host "[ERROR] 找不到 $sqlFile" -ForegroundColor Red
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  智能评估系统 - MySQL 初始化" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  主机: ${HostName}:${Port}" -ForegroundColor Gray
Write-Host "  用户: $User" -ForegroundColor Gray
Write-Host "  数据库: $Database" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan

if (-not $SkipConfirm) {
    $confirm = Read-Host "`n确认执行？(y/n)"
    if ($confirm -ne 'y') {
        Write-Host "已取消" -ForegroundColor Yellow
        exit 0
    }
}

# 查找 mysql 客户端
$mysqlExe = $null
$searchPaths = @(
    "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
    "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe",
    "C:\Program Files\MySQL\MySQL Server 9.0\bin\mysql.exe",
    "mysql.exe"
)
foreach ($p in $searchPaths) {
    if (Get-Command $p -ErrorAction SilentlyContinue) {
        $mysqlExe = $p
        break
    }
}

if (-not $mysqlExe) {
    Write-Host "`n[ERROR] 未找到 MySQL 客户端 (mysql.exe)" -ForegroundColor Red
    Write-Host "请安装 MySQL 或将 mysql.exe 所在目录加入 PATH" -ForegroundColor Yellow
    Write-Host "或手动执行: mysql -u root -p < init-mysql.sql" -ForegroundColor Yellow
    exit 1
}

Write-Host "`n执行 SQL 脚本..." -ForegroundColor Yellow

$cmd = "`"$mysqlExe`" -h $HostName -P $Port -u $User -p`"$Password`" --default-character-set=utf8mb4 < `"$sqlFile`""
$result = cmd /c $cmd 2>&1
$exitCode = $LASTEXITCODE

Write-Host $result

if ($exitCode -eq 0) {
    Write-Host "`n[OK] MySQL 初始化成功！" -ForegroundColor Green
} else {
    Write-Host "`n[FAIL] 初始化失败 (exit code: $exitCode)" -ForegroundColor Red
    exit $exitCode
}
