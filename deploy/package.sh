#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGE_NAME="assessment-centos7-deploy-$(date +%Y%m%d-%H%M)"

echo "========================================"
echo "智能评估系统 - 完整部署包打包"
echo "========================================"
echo ""
echo "此脚本将创建完整的离线部署包，包含："
echo "  - 项目完整源代码"
echo "  - 所有 Dockerfile"
echo "  - 构建和部署脚本"
echo "  - CentOS 7.9 部署配置"
echo ""

cd "$PROJECT_DIR"

echo "[1] 确保前端已构建..."
if [[ ! -f "frontend/dist/index.html" ]]; then
    log_warn "前端未构建, 尝试构建..."
    cd frontend && npm install && npm run build || npx vite build || {
        log_error "前端构建失败, 请手动执行: cd frontend && npm run build"
        exit 1
    }
    cd "$PROJECT_DIR"
fi
echo "  前端 dist 就绪"

echo ""
echo "[2] 打包项目文件..."
PACKAGE_FILES=(
    "frontend/dist"
    "frontend/package.json"
    "frontend/vite.config.ts"
    "frontend/tsconfig.json"
    "frontend/tsconfig.node.json"
    "frontend/index.html"
    "frontend/src"
    "python"
    "java"
    "docker"
    "deploy"
    "docker-compose.yml"
    "PRD.md"
    "README.md"
)

TAR_ARGS=""
for f in "${PACKAGE_FILES[@]}"; do
    if [[ -e "$f" ]]; then
        TAR_ARGS="$TAR_ARGS $f"
    fi
done

tar -czf "${PACKAGE_NAME}.tar.gz" $TAR_ARGS
PACKAGE_SIZE=$(du -h "${PACKAGE_NAME}.tar.gz" | cut -f1)

echo ""
echo "========================================"
echo "打包完成!"
echo "========================================"
echo ""
echo "包名: ${PACKAGE_NAME}.tar.gz"
echo "大小: ${PACKAGE_SIZE}"
echo "位置: $PROJECT_DIR/${PACKAGE_NAME}.tar.gz"
echo ""
echo "========================================"
echo "部署流程:"
echo "========================================"
echo ""
echo "┌─ 步骤1: 在联网机器上构建 Docker 镜像 ─────────────────┐"
echo "│                                                       │"
echo "│  tar -xzf ${PACKAGE_NAME}.tar.gz                      │"
echo "│  cd intelligent-assessment-system                     │"
echo "│  bash deploy/build-images.sh                          │"
echo "│                                                       │"
echo "│  这将在 docker-images/ 目录生成所有 .tar 镜像文件      │"
echo "│                                                       │"
echo "└───────────────────────────────────────────────────────┘"
echo "                          │"
echo "                          ▼"
echo "┌─ 步骤2: 传输到 CentOS 7.9 内网服务器 ────────────────┐"
echo "│                                                       │"
echo "│  cd .. && tar -czf assessment-final.tar.gz \\         │"
echo "│    intelligent-assessment-system/docker-images/ \\     │"
echo "│    intelligent-assessment-system/deploy/               │"
echo "│                                                       │"
echo "│  scp assessment-final.tar.gz root@<IP>:/opt/          │"
echo "│                                                       │"
echo "└───────────────────────────────────────────────────────┘"
echo "                          │"
echo "                          ▼"
echo "┌─ 步骤3: 在 CentOS 7.9 上部署 ────────────────────────┐"
echo "│                                                       │"
echo "│  ssh root@<IP>                                        │"
echo "│  cd /opt && tar -xzf assessment-final.tar.gz          │"
echo "│  cd intelligent-assessment-system                     │"
echo "│  bash deploy/deploy-centos7.sh                        │"
echo "│  cd /opt/intelligent-assessment && bash start.sh      │"
echo "│                                                       │"
echo "└───────────────────────────────────────────────────────┘"
echo ""
echo "========================================"
