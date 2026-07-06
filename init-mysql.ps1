# ============================================================
# 智能评估系统 - MySQL 一键初始化脚本
# 用法：.\init-mysql.ps1
#       或 .\init-mysql.ps1 -Host 192.168.1.100 -User root -Password mypass
# ============================================================

param(
    [string]$HostName = $env:MYSQL_HOST ?? "localhost",
    [string]$Port     = $env:MYSQL_PORT ?? "3306",
    [string]$User     = $env:MYSQL_USER ?? "root",
    [string]$Password = $env:MYSQL_PASSWORD ?? "root",
    [string]$Database = $env:MYSQL_DATABASE ?? "assessment",
    [switch]$SkipConfirm
)

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
