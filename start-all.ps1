# ============================================================
# 统一启动脚本：智能评估系统 + AEGIS 动态本体（Palantir）模块
# ------------------------------------------------------------
# 用法：
#   .\start-all.ps1             # 使用已有镜像启动全部服务
#   .\start-all.ps1 -Build      # 重新构建全部镜像后启动（耗时较长）
#   .\start-all.ps1 -SkipSeed   # 跳过 AEGIS 种子数据灌入
#
# 服务端口：
#   智能评估系统  前端 10086 / 服务 10252-10258 / Qdrant 6333
#   AEGIS         前端 3000 / API 5000 / Neo4j 7474,7687 / OpenSearch 9200 / Redis 6379
# ============================================================

param(
  [switch]$Build,
  [switch]$SkipSeed
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# ---------- 1. 校验 .env ----------
if (-not (Test-Path "$root\.env")) {
  Write-Host "[start-all] 未找到 .env，请先执行: copy .env.example .env" -ForegroundColor Yellow
  exit 1
}
Write-Host "[start-all] .env 校验通过" -ForegroundColor Green

# ---------- 2. 构建镜像（可选） ----------
if ($Build) {
  Write-Host "[start-all] 构建智能评估系统镜像..." -ForegroundColor Cyan
  & "$root\build-all.ps1"
  if ($LASTEXITCODE -ne 0) { Write-Host "[start-all] build-all.ps1 失败，退出" -ForegroundColor Red; exit 1 }

  Write-Host "[start-all] 构建 AEGIS 镜像（api / frontend）..." -ForegroundColor Cyan
  docker compose -f "$root\docker-compose.aegis.yml" build
  if ($LASTEXITCODE -ne 0) { Write-Host "[start-all] AEGIS 镜像构建失败，退出" -ForegroundColor Red; exit 1 }
}

# ---------- 3. 统一拉起全部服务 ----------
Write-Host "[start-all] 启动智能评估系统 + AEGIS 全部服务（docker compose）..." -ForegroundColor Cyan
docker compose -f "$root\docker-compose.yml" -f "$root\docker-compose.aegis.yml" up -d

# ---------- 4. 等待 AEGIS API 就绪（TCP 端口探测） ----------
Write-Host "[start-all] 等待 AEGIS API 就绪（localhost:5000）..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 45; $i++) {
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $client.Connect('localhost', 5000)
    $ready = $true
    break
  } catch {
    Start-Sleep -Seconds 2
  } finally {
    $client.Dispose()
  }
}
if (-not $ready) {
  Write-Host "[start-all] 警告: AEGIS API 未在预期时间内就绪，请检查: docker compose -f docker-compose.aegis.yml logs api" -ForegroundColor Yellow
} else {
  Write-Host "[start-all] AEGIS API 已就绪" -ForegroundColor Green
}

# ---------- 5. AEGIS 种子数据（幂等，可重复执行） ----------
if (-not $SkipSeed -and $ready) {
  Write-Host "[start-all] 灌入 AEGIS 种子数据（POST /api/seed，幂等）..." -ForegroundColor Cyan
  $seedOk = $false
  for ($j = 0; $j -lt 2 -and -not $seedOk; $j++) {
    try {
      Invoke-RestMethod -Uri "http://localhost:5000/api/seed" -Method Post -TimeoutSec 180 | Out-Null
      $seedOk = $true
    } catch {
      Write-Host "[start-all] seed 第 $($j + 1) 次尝试失败: $($_.Exception.Message)" -ForegroundColor Yellow
      Start-Sleep -Seconds 5
    }
  }
  if ($seedOk) { Write-Host "[start-all] AEGIS 种子数据灌入完成" -ForegroundColor Green }
  else { Write-Host "[start-all] seed 未成功，可稍后手动执行: Invoke-RestMethod -Uri http://localhost:5000/api/seed -Method Post" -ForegroundColor Yellow }
}

# ---------- 6. 输出访问地址 ----------
Write-Host ""
Write-Host "====================== 服务就绪 ======================" -ForegroundColor Green
Write-Host "智能评估系统前端 : http://localhost:10086   （本体模型 → 顶部「动态本体」卡片）" -ForegroundColor White
Write-Host "AEGIS 动态本体   : http://localhost:3000" -ForegroundColor White
Write-Host "AEGIS API        : http://localhost:5000" -ForegroundColor White
Write-Host "Neo4j Browser    : http://localhost:7474" -ForegroundColor White
Write-Host "OpenSearch       : http://localhost:9200" -ForegroundColor White
Write-Host "=====================================================" -ForegroundColor Green
