#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGES_DIR="$PROJECT_DIR/docker-images"
mkdir -p "$IMAGES_DIR"

echo "========================================"
echo "智能评估系统 - Docker 镜像构建脚本"
echo "========================================"
echo ""

build_image() {
    local name=$1
    local dockerfile=$2
    echo "[构建] $name ..."
    docker build -t "assessment-$name:latest" \
        -f "$PROJECT_DIR/docker/Dockerfile.$dockerfile" \
        "$PROJECT_DIR"
}

save_image() {
    local name=$1
    echo "[导出] assessment-$name:latest -> $IMAGES_DIR/assessment-$name.tar"
    docker save -o "$IMAGES_DIR/assessment-$name.tar" "assessment-$name:latest"
}

echo "=== 第1步: 构建前端 ==="
build_image "frontend" "frontend"
save_image "frontend"

echo ""
echo "=== 第2步: 构建 Python 服务 ==="
build_image "knowledge" "knowledge"
save_image "knowledge"

build_image "qa" "qa"
save_image "qa"

build_image "indicator" "indicator"
save_image "indicator"

build_image "evaluation" "evaluation"
save_image "evaluation"

build_image "ontology" "ontology"
save_image "ontology"

build_image "solution-evaluation" "solution-evaluation"
save_image "solution-evaluation"

echo ""
echo "=== 第3步: 构建 Java 服务 ==="
build_image "gateway" "gateway"
save_image "gateway"

build_image "admin" "admin"
save_image "admin"

echo ""
echo "========================================"
echo "所有镜像构建完成!"
echo "========================================"
echo ""
echo "镜像文件位于: $IMAGES_DIR/"
ls -lh "$IMAGES_DIR/"
echo ""
echo "下一步: 将整个项目传输到 CentOS 7.9 服务器"
echo "  tar -czf assessment-deploy.tar.gz docker-images/ deploy/ docker-compose.yml"
echo "  scp assessment-deploy.tar.gz root@<服务器IP>:/opt/"
echo ""
echo "在服务器上执行:"
echo "  cd /opt && tar -xzf assessment-deploy.tar.gz"
echo "  bash deploy/deploy-centos7.sh"
