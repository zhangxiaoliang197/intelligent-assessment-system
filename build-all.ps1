# ========================================
# 智能评估系统 - Docker 镜像构建 (Windows)
# 
# 使用方法:
#   1. 确保 Docker Desktop 已启动并正常运行
#   2. 在此项目根目录右键 -> "Open in Terminal"
#   3. 运行: .\build-all.ps1
# ========================================
param()

$ErrorActionPreference = "Stop"
$PROJECT = "$PSScriptRoot"
$IMAGES_DIR = "$PROJECT\docker-images"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "智能评估系统 - Docker 镜像构建 (Windows)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---- 检查 Docker ----
Write-Host "[检查] Docker 环境..." -ForegroundColor Yellow
try {
    $dockerVer = docker --version 2>&1
    Write-Host "  Docker CLI: $dockerVer" -ForegroundColor Green
    docker info 2>&1 | Out-Null
    Write-Host "  Docker Engine: 运行中" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Docker 未运行! 请先启动 Docker Desktop" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $IMAGES_DIR | Out-Null

# ---- 构建函数 ----
function Build-And-Save {
    param($ImageName, $Dockerfile, $Port, $Desc)
    
    Write-Host ""
    Write-Host ">>> 构建 $Desc ($ImageName) 端口:$Port ..." -ForegroundColor Blue

    docker build `
        -t "assessment-${ImageName}:latest" `
        -f "$PROJECT\docker\Dockerfile.$Dockerfile" `
        "$PROJECT"

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: 构建 $ImageName 失败!" -ForegroundColor Red
        exit 1
    }

    Write-Host ">>> 导出 assessment-$ImageName.tar ..." -ForegroundColor Green
    docker save -o "$IMAGES_DIR\assessment-$ImageName.tar" "assessment-${ImageName}:latest"

    $size = (Get-Item "$IMAGES_DIR\assessment-$ImageName.tar").Length / 1MB
    Write-Host "  [OK] assessment-$ImageName.tar ($([math]::Round($size, 1)) MB)" -ForegroundColor Green
}

# ---- 阶段1: Python 服务 (5个) ----
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "阶段 1/3: 构建 Python 微服务 (5个)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Build-And-Save "knowledge"   "knowledge"   "8001" "知识库服务"
Build-And-Save "qa"          "qa"          "8002" "智能问答服务"
Build-And-Save "indicator"   "indicator"   "8003" "指标分析服务"
Build-And-Save "evaluation"  "evaluation"  "8004" "方案评估服务"
Build-And-Save "ontology"    "ontology"    "8005" "本体模型服务"

# ---- 阶段2: Java 服务 (2个) ----
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "阶段 2/3: 构建 Java 服务 (2个)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Build-And-Save "gateway"     "gateway"     "8080" "API网关服务"
Build-And-Save "admin"       "admin"       "8081" "基础管理服务"

# ---- 阶段3: 前端 ----
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "阶段 3/3: 构建前端" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Build-And-Save "frontend"    "frontend"    "80"   "前端界面"

# ---- 汇总 ----
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "全部 8 个镜像构建完成!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Get-ChildItem $IMAGES_DIR | ForEach-Object {
    $sizeMB = [math]::Round($_.Length / 1MB, 1)
    Write-Host "  $($_.Name)  ($sizeMB MB)"
}

$totalMB = [math]::Round((Get-ChildItem $IMAGES_DIR | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "镜像总大小: $totalMB MB" -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "下一步 - 打包传输到内网 CentOS 7.9:" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  将 docker-images\ 文件夹 + deploy\ 文件夹 拷贝到 CentOS 7.9 的 /opt/ 目录"
Write-Host ""
Write-Host "  在 CentOS 7.9 上执行:"
Write-Host "    cd /opt/intelligent-assessment-system"
Write-Host "    bash deploy/deploy-centos7.sh"
Write-Host "========================================" -ForegroundColor Cyan
