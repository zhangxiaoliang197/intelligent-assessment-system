#!/bin/bash
# ========================================
# 智能评估系统 - Docker run 启动脚本
# 适用于: Docker 无 docker compose 插件的环境
# 用法: bash start-docker-run.sh [MYSQL_HOST] [MYSQL_USER] [MYSQL_PASSWORD]
#   bash start-docker-run.sh                           # 默认连宿主机MySQL (root/root)
#   bash start-docker-run.sh 192.168.1.100             # 指定MySQL IP
#   bash start-docker-run.sh 192.168.1.100 root mypass # 指定全部
# ========================================

NET_NAME="assessment-net"
BASE_DIR="/opt/intelligent-assessment"

# ─── MySQL 连接参数 ───
MYSQL_HOST="${1:-172.17.0.1}"
MYSQL_USER="${2:-root}"
MYSQL_PASSWORD="${3:-root}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATABASE="${MYSQL_DATABASE:-assessment}"

echo "========================================"
echo "智能评估系统 - Docker 启动脚本"
echo "========================================"
echo "  MySQL: ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}"
# ─── 宿主机数据目录 (重启不丢失) ───
DATA_DIR="$BASE_DIR/data"
mkdir -p "$DATA_DIR/drivers"
mkdir -p "$DATA_DIR/knowledge"
mkdir -p "$DATA_DIR/qa"
mkdir -p "$DATA_DIR/ontology"
mkdir -p "$DATA_DIR/evaluation"
mkdir -p "$DATA_DIR/solution-eval"
mkdir -p "$DATA_DIR/config"

echo "  数据目录: $DATA_DIR"

QUERIES_FILE="$DATA_DIR/config/queries.json"
if [ ! -f "$QUERIES_FILE" ]; then
    echo "  首次部署: 复制 queries.json 模板到 $QUERIES_FILE"
    cp "$BASE_DIR/deploy/queries.json" "$QUERIES_FILE" 2>/dev/null || \
        cp "/opt/intelligent-assessment/deploy/queries.json" "$QUERIES_FILE" 2>/dev/null || \
        echo '[]' > "$QUERIES_FILE"
fi

# ─── 创建网络 ───
docker network inspect "$NET_NAME" >/dev/null 2>&1 || \
    docker network create "$NET_NAME"

# ─── 0. 等待 MySQL 就绪 ───
echo "========================================"
echo "[0/9] 等待 MySQL 就绪..."
echo "========================================"
echo "  MySQL: ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}"

# 简单 TCP 端口探测，不需要 mysql 客户端
for i in $(seq 1 30); do
    if timeout 2 bash -c "echo >/dev/tcp/${MYSQL_HOST}/${MYSQL_PORT}" 2>/dev/null; then
        echo "  MySQL 端口已开放 (${i}s)"
        break
    fi
    # 兜底：用 docker run 一个临时 mysql 客户端检测
    if [ $i -eq 10 ]; then
        docker run --rm --network "$NET_NAME" \
            mysql:5.7 \
            mysqladmin ping -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" 2>/dev/null && \
            echo "  MySQL 可连接" && break
    fi
    if [ $i -eq 30 ]; then
        echo "  WARNING: MySQL 未就绪，admin 服务启动可能失败"
    fi
    sleep 1
done
echo "  (admin 服务启动后将自动建库建表)"

# ─── 1-6. Python 服务 ───
echo ""
echo "========================================"
echo "[1/9] 启动 Python 服务..."
echo "========================================"

echo "[启动] 知识库服务 (10252)..."
docker run -d --name assessment-knowledge \
    --network "$NET_NAME" \
    -p 10252:10252 \
    -v "$DATA_DIR/knowledge:/app/data" \
    --restart always \
    assessment-knowledge:latest

echo "[启动] 智能问答服务 (10253)..."
docker run -d --name assessment-qa \
    --network "$NET_NAME" \
    -p 10253:10253 \
    -e ADMIN_SERVICE_URL="http://assessment-admin:10258" \
    -e KNOWLEDGE_SERVICE_URL="http://assessment-knowledge:10252" \
    -v "$DATA_DIR/qa:/app/data" \
    --restart always \
    assessment-qa:latest

echo "[启动] 指标分析服务 (10254)..."
docker run -d --name assessment-indicator \
    --network "$NET_NAME" \
    -p 10254:10254 \
    -e QA_SERVICE_URL="http://assessment-qa:10253" \
    -e ADMIN_SERVICE_URL="http://assessment-admin:10258" \
    --restart always \
    assessment-indicator:latest

echo "[启动] 方案评估服务 (10255)..."
docker run -d --name assessment-evaluation \
    --network "$NET_NAME" \
    -p 10255:10255 \
    -v "$DATA_DIR/evaluation:/app/data" \
    --restart always \
    assessment-evaluation:latest

echo "[启动] 本体模型服务 (10256)..."
docker run -d --name assessment-ontology \
    --network "$NET_NAME" \
    -p 10256:10256 \
    -v "$DATA_DIR/ontology:/app/data" \
    --restart always \
    assessment-ontology:latest

echo "[启动] 方案评估服务(多Agent) (10259)..."
docker run -d --name assessment-solution-evaluation \
    --network "$NET_NAME" \
    -p 10259:10259 \
    -e QA_SERVICE_URL="http://assessment-qa:10253" \
    -e INDICATOR_SERVICE_URL="http://assessment-indicator:10254" \
    -e ADMIN_SERVICE_URL="http://assessment-admin:10258" \
    -e COMBAT_QUERIES_PATH="/app/queries-custom.json" \
    -v "$DATA_DIR/solution-eval:/app/data" \
    -v "$DATA_DIR/config/queries.json:/app/queries-custom.json:ro" \
    --restart always \
    assessment-solution-evaluation:latest

# ─── 7-8. Java 服务 (需要 MySQL 环境变量) ───
echo ""
echo "========================================"
echo "[2/9] 启动 Java 服务..."
echo "========================================"

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
    -v "$DATA_DIR/drivers:/app/drivers" \
    --restart always \
    -e MYSQL_HOST="$MYSQL_HOST" \
    -e MYSQL_PORT="$MYSQL_PORT" \
    -e MYSQL_DATABASE="$MYSQL_DATABASE" \
    -e MYSQL_USER="$MYSQL_USER" \
    -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
    -e DB_TYPE="mysql" \
    assessment-admin:latest

# ─── 9. 等待网关就绪后启动前端 ───
echo ""
echo "========================================"
echo "[3/9] 等待 API网关就绪..."
echo "========================================"
for i in $(seq 1 90); do
    if curl -s http://127.0.0.1:10257/actuator/health >/dev/null 2>&1; then
        echo "  API网关已就绪 (${i}s)"
        break
    fi
    if [ $i -eq 90 ]; then
        echo "  WARNING: API网关超时, 前端启动可能失败"
    fi
    sleep 1
done

echo "[启动] 前端界面 (10086)..."
docker run -d --name assessment-frontend \
    --network "$NET_NAME" \
    -p 10086:80 \
    --restart always \
    assessment-frontend:latest

# ─── 状态汇总 ───
echo ""
echo "========================================"
echo "  服务状态"
echo "========================================"
docker ps --filter "name=assessment" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$IP" ] && IP="<服务器IP>"
echo "  访问地址: http://${IP}:10086"
echo "  MySQL:    ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}"
echo "  共启动 9 个服务"
echo "========================================"
