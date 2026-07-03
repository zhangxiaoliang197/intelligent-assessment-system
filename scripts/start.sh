#!/bin/bash

echo "========================================"
echo "智能评估系统 - 启动脚本"
echo "========================================"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "正在启动所有服务..."
docker-compose up -d

echo ""
echo "等待服务启动..."
sleep 10

echo ""
echo "========================================"
echo "服务状态："
echo "========================================"
docker-compose ps

echo ""
echo "========================================"
echo "访问地址："
echo "========================================"
echo "前端界面: http://localhost:3000"
echo "API网关:  http://localhost:8080"
echo "知识库服务: http://localhost:8001"
echo "智能问答服务: http://localhost:8002"
echo "指标分析服务: http://localhost:8003"
echo "方案评估服务: http://localhost:8004"
echo "本体模型服务: http://localhost:8005"
echo "基础管理服务: http://localhost:8081"
echo "Neo4j图数据库: http://localhost:7474"
echo "========================================"
