#!/bin/bash

echo "========================================"
echo "智能评估系统 - 离线部署脚本"
echo "========================================"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "1. 导出Docker镜像..."
docker save -o docker/images/admin-service.tar admin-service:latest
docker save -o docker/images/api-gateway.tar api-gateway:latest
docker save -o docker/images/knowledge-service.tar knowledge-service:latest
docker save -o docker/images/qa-service.tar qa-service:latest
docker save -o docker/images/indicator-service.tar indicator-service:latest
docker save -o docker/images/evaluation-service.tar evaluation-service:latest
docker save -o docker/images/ontology-service.tar ontology-service:latest
docker save -o docker/images/frontend.tar frontend:latest

echo "镜像导出完成"

echo ""
echo "2. 复制依赖文件..."
cp -r python/*/requirements.txt docker/
cp -r java/*/pom.xml docker/
cp -r java/*/src docker/

echo "依赖文件复制完成"

echo ""
echo "3. 创建部署包..."
tar -czf intelligent-assessment-system-$(date +%Y%m%d).tar.gz \
  docker/ \
  docker-compose.yml \
  frontend/package.json \
  frontend/src/ \
  frontend/vite.config.ts \
  frontend/index.html

echo "部署包创建完成: intelligent-assessment-system-$(date +%Y%m%d).tar.gz"

echo ""
echo "========================================"
echo "离线部署包准备完成！"
echo "========================================"
