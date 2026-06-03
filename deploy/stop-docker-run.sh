#!/bin/bash
# ========================================
# 智能评估系统 - Docker 停止脚本
# 用法: bash stop-docker-run.sh
# ========================================

echo "智能评估系统 - 停止所有服务..."

SERVICES=(
    assessment-frontend
    assessment-admin
    assessment-gateway
    assessment-ontology
    assessment-evaluation
    assessment-indicator
    assessment-qa
    assessment-knowledge
)

for svc in "${SERVICES[@]}"; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${svc}$"; then
        docker stop "$svc" 2>/dev/null
        docker rm "$svc" 2>/dev/null
        echo "[停止] $svc"
    fi
done

docker network rm assessment-net 2>/dev/null && echo "[清理] 删除网络 assessment-net"
echo ""
echo "所有服务已停止"
