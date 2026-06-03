#!/bin/bash
# ========================================
# 智能评估系统 - Docker 镜像一键构建脚本
# 用途: 在联网的机器上构建所有 docker 镜像并导出为 tar
# 使用: bash build-all.sh
# ========================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGES_DIR="$PROJECT_DIR/docker-images"
mkdir -p "$IMAGES_DIR"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "========================================"
echo "智能评估系统 - Docker 镜像构建"
echo "========================================"
echo ""

build_and_save() {
    local IMAGE_NAME=$1
    local DOCKERFILE=$2
    local PORT=$3
    local DESC=$4

    echo -e "${BLUE}>>> 构建 $DESC ($IMAGE_NAME) ...${NC}"
    docker build \
        -t "assessment-$IMAGE_NAME:latest" \
        -f "$PROJECT_DIR/docker/Dockerfile.$DOCKERFILE" \
        "$PROJECT_DIR"

    echo -e "${GREEN}>>> 导出 assessment-$IMAGE_NAME.tar${NC}"
    docker save -o "$IMAGES_DIR/assessment-$IMAGE_NAME.tar" "assessment-$IMAGE_NAME:latest"
    echo ""
}

echo "========================================="
echo "阶段 1/3: 构建 Python 微服务 (5个)"
echo "========================================="
echo ""

build_and_save "knowledge"   "knowledge"   "8001" "知识库服务"
build_and_save "qa"          "qa"          "8002" "智能问答服务"
build_and_save "indicator"   "indicator"   "8003" "指标分析服务"
build_and_save "evaluation"  "evaluation"  "8004" "方案评估服务"
build_and_save "ontology"    "ontology"    "8005" "本体模型服务"

echo "========================================="
echo "阶段 2/3: 构建 Java 服务 (2个)"
echo "========================================="
echo ""

build_and_save "gateway"     "gateway"     "8080" "API网关服务"
build_and_save "admin"       "admin"       "8081" "基础管理服务"

echo "========================================="
echo "阶段 3/3: 构建前端"
echo "========================================="
echo ""

build_and_save "frontend"    "frontend"    "80"   "前端界面"

echo ""
echo "========================================"
echo -e "${GREEN}全部 8 个镜像构建完成!${NC}"
echo "========================================"
echo ""
echo "镜像文件位于: $IMAGES_DIR/"
ls -lh "$IMAGES_DIR/"
echo ""
echo "镜像总大小: $(du -sh "$IMAGES_DIR" | cut -f1)"
echo ""
echo "========================================"
echo "下一步 - 打包传输到内网 CentOS 7.9:"
echo "========================================"
echo ""
echo "  cd .."
echo "  tar -czf assessment-images.tar.gz \\"
echo "    intelligent-assessment-system/docker-images/ \\"
echo "    intelligent-assessment-system/deploy/"
echo ""
echo "  scp assessment-images.tar.gz root@<内网IP>:/opt/"
echo ""
echo "然后在 CentOS 7.9 上执行:"
echo "  cd /opt && tar -xzf assessment-images.tar.gz"
echo "  cd intelligent-assessment-system"
echo "  bash deploy/deploy-centos7.sh"
echo "========================================"
