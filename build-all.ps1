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

# ---- 同步公共日志配置到各 Python 服务目录 ----
Write-Host ">>> 同步 logging_config.py 到各 Python 服务..." -ForegroundColor Yellow
$services = @("knowledge-service","qa-service","indicator-service","evaluation-service","ontology-service","situation-service")
$srcLogConfig = "$PROJECT\python\common\logging_config.py"
foreach ($svc in $services) {
    $dst = "$PROJECT\python\$svc\logging_config.py"
    Copy-Item -Path $srcLogConfig -Destination $dst -Force
}
Write-Host "  同步完成" -ForegroundColor Green
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

    if ($ImageName -eq "qa") {
        Write-Host ">>> 校验 QA 镜像内 Skill 目录..." -ForegroundColor Yellow
        $pyCode = @'
from agents.skill_catalog import load_catalog; catalog=load_catalog(); assert len(catalog["skills"]) == 30; print("Skill catalog OK:", len(catalog["skills"]))
'@
        docker run --rm --entrypoint python "assessment-${ImageName}:latest" -c $pyCode
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: QA 镜像缺少或无法加载 /app/config/skills 目录，停止导出!" -ForegroundColor Red
            exit 1
        }
    }
    if ($ImageName -eq "situation") {
        Write-Host ">>> 运行态势 Skill 测试与目录校验..." -ForegroundColor Yellow
        docker run --rm --entrypoint python "assessment-${ImageName}:latest" -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: 态势 Skill 测试失败，停止导出!" -ForegroundColor Red
            exit 1
        }
    }

    Write-Host ">>> 导出 assessment-$ImageName.tar ..." -ForegroundColor Green
    docker save -o "$IMAGES_DIR\assessment-$ImageName.tar" "assessment-${ImageName}:latest"

    $size = (Get-Item "$IMAGES_DIR\assessment-$ImageName.tar").Length / 1MB
    Write-Host "  [OK] assessment-$ImageName.tar ($([math]::Round($size, 1)) MB)" -ForegroundColor Green
}

# ---- 阶段1: Python 服务 (6个) ----
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "阶段 1/4: 构建 Python 微服务 (6个)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Build-And-Save "knowledge"             "knowledge"             "10252" "知识库服务"
Build-And-Save "qa"                    "qa"                    "10253" "智能问答服务"
Build-And-Save "indicator"             "indicator"             "10254" "指标分析服务"
Build-And-Save "evaluation"            "evaluation"            "10255" "评估分析服务"
Build-And-Save "ontology"              "ontology"              "10256" "本体模型服务"
Build-And-Save "situation"             "situation"             "10257" "态势图服务"

# ---- 阶段2: Java 服务 (1个) ----
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "阶段 2/4: 构建 Java 服务 (1个)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Build-And-Save "admin"       "admin"       "10258" "基础管理服务"

# ---- 阶段3: 前端 ----
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "阶段 3/4: 构建前端" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Build-And-Save "frontend"    "frontend"    "80"   "前端界面"

# ---- 阶段4: Qdrant (拉取第三方镜像) ----
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "阶段 4/4: 拉取 Qdrant 向量数据库镜像" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host ">>> 拉取 qdrant/qdrant:latest ..." -ForegroundColor Blue
docker pull qdrant/qdrant:latest
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: 拉取 Qdrant 镜像失败!" -ForegroundColor Red
    exit 1
}

Write-Host ">>> 导出 assessment-qdrant.tar ..." -ForegroundColor Green
docker save -o "$IMAGES_DIR\assessment-qdrant.tar" "qdrant/qdrant:latest"
$size = (Get-Item "$IMAGES_DIR\assessment-qdrant.tar").Length / 1MB
Write-Host "  [OK] assessment-qdrant.tar ($([math]::Round($size, 1)) MB)" -ForegroundColor Green

# ---- 汇总 ----
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "全部 9 个镜像构建完成!" -ForegroundColor Green
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
