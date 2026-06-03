#!/bin/bash
# ========================================
# 智能评估系统 - Docker run 启动脚本
# 适用于: Docker 无 docker compose 插件的环境
# 用法: bash start-docker-run.sh
# ========================================

NET_NAME="assessment-net"
BASE_DIR="/opt/intelligent-assessment"

echo "智能评估系统 - Docker 启动脚本 (docker run 模式)"
echo ""

# 创建网络
docker network inspect "$NET_NAME" >/dev/null 2>&1 || \
    docker network create "$NET_NAME"

echo "[启动] 知识库服务 (10252)..."
docker run -d --name assessment-knowledge \
    --network "$NET_NAME" \
    -p 10252:10252 \
    --restart always \
    assessment-knowledge:latest

echo "[启动] 智能问答服务 (10253)..."
docker run -d --name assessment-qa \
    --network "$NET_NAME" \
    -p 10253:10253 \
    --restart always \
    assessment-qa:latest

echo "[启动] 指标分析服务 (10254)..."
docker run -d --name assessment-indicator \
    --network "$NET_NAME" \
    -p 10254:10254 \
    --restart always \
    assessment-indicator:latest

echo "[启动] 方案评估服务 (10255)..."
docker run -d --name assessment-evaluation \
    --network "$NET_NAME" \
    -p 10255:10255 \
    --restart always \
    assessment-evaluation:latest

echo "[启动] 本体模型服务 (10256)..."
docker run -d --name assessment-ontology \
    --network "$NET_NAME" \
    -p 10256:10256 \
    --restart always \
    assessment-ontology:latest

echo "[启动] API网关服务 (10257)..."
docker run -d --name assessment-gateway \
    --network "$NET_NAME" \
    -p 10257:10257 \
    --restart always \
    assessment-gateway:latest

echo "[启动] 基础管理服务 (10258)..."
docker run -d --name assessment-admin \
    --network "$NET_NAME" \
    -p 10258:10258 \
    --restart always \
    assessment-admin:latest

echo "[启动] 前端界面 (10086)..."
docker run -d --name assessment-frontend \
    --network "$NET_NAME" \
    -p 10086:80 \
    --restart always \
    assessment-frontend:latest

echo ""
echo "等待服务就绪..."
sleep 5
echo ""
echo "========================================"
echo "服务状态:"
echo "========================================"
docker ps --filter "name=assessment" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
IP=$(hostname -I | awk '{print $1}')
echo "访问地址: http://${IP}:10086"
echo "========================================"
