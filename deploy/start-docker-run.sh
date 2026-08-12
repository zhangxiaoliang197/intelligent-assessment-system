#!/bin/bash
set -euo pipefail

# ========================================
# 智能评估系统 - Docker run 启动脚本
# 适用于: Docker 无 docker compose 插件的环境
# 用法: bash start-docker-run.sh [MYSQL_HOST] [MYSQL_USER] [MYSQL_PASSWORD]
#   bash start-docker-run.sh 192.168.1.100             # 指定远程MySQL IP
#   bash start-docker-run.sh 192.168.1.100 root mypass # 指定全部
#   或通过环境变量：MYSQL_HOST=192.168.1.100 MYSQL_PASSWORD=xxx bash start-docker-run.sh
# 注意: MYSQL_HOST 无默认值，必须通过参数或环境变量显式配置。
# ========================================

NET_NAME="assessment-net"
BASE_DIR="/opt/intelligent-assessment"

# ─── MySQL 连接参数 ───
MYSQL_HOST="${1:-${MYSQL_HOST:-}}"
MYSQL_USER="${2:-${MYSQL_USER:-root}}"
MYSQL_PASSWORD="${3:-${MYSQL_PASSWORD:-}}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATABASE="${MYSQL_DATABASE:-assessment}"
DB_TYPE="${DB_TYPE:-mysql}"

# ─── Qdrant 连接参数 ───
QDRANT_HOST="${QDRANT_HOST:-assessment-qdrant}"
QDRANT_PORT="${QDRANT_PORT:-6333}"

# 校验：MYSQL_HOST 必须显式配置
if [ -z "$MYSQL_HOST" ]; then
    echo "ERROR: MYSQL_HOST 未配置。请通过参数或环境变量指定元数据库地址。"
    echo "  用法: bash start-docker-run.sh <MYSQL_HOST> [MYSQL_USER] [MYSQL_PASSWORD]"
    echo "  示例: bash start-docker-run.sh 192.168.1.100 root mypass"
    echo "  或:   MYSQL_HOST=192.168.1.100 bash start-docker-run.sh"
    exit 1
fi

echo "========================================"
echo "智能评估系统 - Docker 启动脚本"
echo "========================================"
echo "  MySQL: ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}"
# ─── 宿主机数据目录 (重启不丢失) ───
DATA_DIR="$BASE_DIR/data"
# drivers 使用 Docker 命名卷（首次自动从镜像内 /app/drivers 复制，无需宿主机目录）
mkdir -p "$DATA_DIR/knowledge"
mkdir -p "$DATA_DIR/qdrant"
mkdir -p "$DATA_DIR/qa"
mkdir -p "$DATA_DIR/ontology"
mkdir -p "$DATA_DIR/evaluation"
mkdir -p "$DATA_DIR/situation"
mkdir -p "$DATA_DIR/config"

# ─── 日志目录（统一日志持久化）───
LOG_DIR_HOST="$BASE_DIR/logs"
mkdir -p "$LOG_DIR_HOST"/{knowledge,qa,indicator,evaluation,ontology,situation,admin}

# ─── 日志环境变量（可被外部环境变量覆盖）───
LOG_ENV="${LOG_ENV:-prod}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-14}"
LOG_MAX_SIZE_MB="${LOG_MAX_SIZE_MB:-100}"
INTERNAL_SERVICE_TOKEN="${INTERNAL_SERVICE_TOKEN:-local-development-token}"

echo "  数据目录: $DATA_DIR"
echo "  日志目录: $LOG_DIR_HOST"

# 从待启动镜像导出并校验同一份内置 Skill 目录，随后以只读目录
# 挂载。这样即使历史容器或错误的整目录挂载曾污染 /app/config，
# 新容器也会得到确定、可审计的 Markdown 文件。
SKILLS_DIR="$DATA_DIR/config/skills"
SKILLS_TMP_DIR="$DATA_DIR/config/skills.tmp.$$"
CATALOG_EXPORT_CONTAINER="assessment-qa-catalog-export-$$"
echo "  校验 QA 镜像内置 Skill 目录..."
docker run --rm --entrypoint python assessment-qa:latest \
    -c "from agents.skill_catalog import load_catalog; catalog=load_catalog(); assert len(catalog['skills']) == 30; print('  Skill catalog OK:', len(catalog['skills']))"
docker rm -f "$CATALOG_EXPORT_CONTAINER" >/dev/null 2>&1 || true
docker create --name "$CATALOG_EXPORT_CONTAINER" assessment-qa:latest >/dev/null
rm -rf "$SKILLS_TMP_DIR"
mkdir -p "$SKILLS_TMP_DIR"
if ! docker cp "$CATALOG_EXPORT_CONTAINER:/app/config/skills/." "$SKILLS_TMP_DIR"; then
    docker rm -f "$CATALOG_EXPORT_CONTAINER" >/dev/null 2>&1 || true
    rm -rf "$SKILLS_TMP_DIR"
    echo "ERROR: 无法从 assessment-qa:latest 导出 /app/config/skills"
    exit 1
fi
docker rm "$CATALOG_EXPORT_CONTAINER" >/dev/null
rm -rf "$SKILLS_DIR"
mv "$SKILLS_TMP_DIR" "$SKILLS_DIR"
test -s "$SKILLS_DIR/README.md"
test "$(find "$SKILLS_DIR" -mindepth 2 -maxdepth 2 -name SKILL.md -type f | wc -l)" -eq 30

QUERIES_FILE="$DATA_DIR/config/queries.json"
if [ ! -f "$QUERIES_FILE" ]; then
    echo "  首次部署: 复制 queries.json 模板到 $QUERIES_FILE"
    cp "$BASE_DIR/deploy/queries.json" "$QUERIES_FILE" 2>/dev/null || \
        cp "/opt/intelligent-assessment/deploy/queries.json" "$QUERIES_FILE" 2>/dev/null || \
        echo '[]' > "$QUERIES_FILE"
fi

AIR_QUERIES_FILE="$DATA_DIR/config/air_queries.json"
if [ ! -f "$AIR_QUERIES_FILE" ]; then
    echo "  首次部署: 复制 air_queries.json 模板到 $AIR_QUERIES_FILE"
    cp "$BASE_DIR/deploy/air_queries.json" "$AIR_QUERIES_FILE" 2>/dev/null || \
        cp "/opt/intelligent-assessment/deploy/air_queries.json" "$AIR_QUERIES_FILE" 2>/dev/null || \
        echo '{"regionRules":{"patterns":[],"placeholder":"{region}","defaultValue":"全部区域"},"groups":[]}' > "$AIR_QUERIES_FILE"
fi

# docker run 不会自动替换同名容器。部署新镜像前精确删除本系统的
# 旧容器，避免名称冲突后继续由旧 QA 容器提供服务。
SERVICE_CONTAINERS=(
    assessment-frontend
    assessment-admin
    assessment-ontology
    assessment-evaluation
    assessment-indicator
    assessment-qa
    assessment-knowledge
    assessment-qdrant
)
for container_name in "${SERVICE_CONTAINERS[@]}"; do
    if docker ps -a --format '{{.Names}}' | grep -qx "$container_name"; then
        echo "  替换旧容器: $container_name"
        docker rm -f "$container_name" >/dev/null
    fi
done

# ─── 创建网络 ───
docker network inspect "$NET_NAME" >/dev/null 2>&1 || \
    docker network create "$NET_NAME"

# ─── 0. Qdrant 向量数据库 ───
echo ""
echo "========================================"
echo "[0/9] 启动 Qdrant 向量数据库..."
echo "========================================"

echo "[启动] Qdrant (6333)..."
docker run -d --name assessment-qdrant \
    --network "$NET_NAME" \
    -p 6333:6333 \
    -v "$DATA_DIR/qdrant:/qdrant/storage" \
    --restart always \
    qdrant/qdrant:latest

# ─── 1. 等待 MySQL 就绪 ───
echo ""
echo "========================================"
echo "[1/9] 等待 MySQL 就绪..."
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
echo "[2/9] 启动 Python 服务..."
echo "========================================"

echo "[启动] 知识库服务 (10252)..."
docker run -d --name assessment-knowledge \
    --network "$NET_NAME" \
    -p 10252:10252 \
    -e QDRANT_URL="http://${QDRANT_HOST}:${QDRANT_PORT}" \
    -e LOG_ENV="$LOG_ENV" \
    -e LOG_LEVEL="$LOG_LEVEL" \
    -e LOG_DIR="/app/logs" \
    -e LOG_RETENTION_DAYS="$LOG_RETENTION_DAYS" \
    -e LOG_MAX_SIZE_MB="$LOG_MAX_SIZE_MB" \
    -v "$DATA_DIR/knowledge:/app/data" \
    -v "$LOG_DIR_HOST/knowledge:/app/logs" \
    --log-driver json-file \
    --log-opt max-size=50m \
    --log-opt max-file=5 \
    --restart always \
    assessment-knowledge:latest

echo "[启动] 智能问答服务 (10253)..."
docker run -d --name assessment-qa \
    --network "$NET_NAME" \
    -p 10253:10253 \
    -e ADMIN_SERVICE_URL="http://assessment-admin:10258" \
    -e KNOWLEDGE_SERVICE_URL="http://assessment-knowledge:10252" \
    -e ONTOLOGY_SERVICE_URL="http://assessment-ontology:10256" \
    -e EVALUATION_SKILLS_DIR="/app/config/skills" \
    -e EVALUATION_SKILL_MD_OVERRIDE_DIR="/app/data/skill-markdown-overrides" \
    -e LOG_ENV="$LOG_ENV" \
    -e LOG_LEVEL="$LOG_LEVEL" \
    -e LOG_DIR="/app/logs" \
    -e LOG_RETENTION_DAYS="$LOG_RETENTION_DAYS" \
    -e LOG_MAX_SIZE_MB="$LOG_MAX_SIZE_MB" \
    -e LOG_ROTATION_MODE="size" \
    -v "$DATA_DIR/qa:/app/data" \
    -v "$SKILLS_DIR:/app/config/skills:ro" \
    -v "$LOG_DIR_HOST/qa:/app/logs" \
    --log-driver json-file \
    --log-opt max-size=50m \
    --log-opt max-file=5 \
    --restart always \
    assessment-qa:latest

echo "[启动] 指标分析服务 (10254)..."
docker run -d --name assessment-indicator \
    --network "$NET_NAME" \
    -p 10254:10254 \
    -e QA_SERVICE_URL="http://assessment-qa:10253" \
    -e ADMIN_SERVICE_URL="http://assessment-admin:10258" \
    -e KNOWLEDGE_SERVICE_URL="http://assessment-knowledge:10252" \
    -e EVALUATION_API_URL="http://assessment-qa:10253" \
    -e ONTOLOGY_SERVICE_URL="http://assessment-ontology:10256" \
    -e LOG_ENV="$LOG_ENV" \
    -e LOG_LEVEL="$LOG_LEVEL" \
    -e LOG_DIR="/app/logs" \
    -e LOG_RETENTION_DAYS="$LOG_RETENTION_DAYS" \
    -e LOG_MAX_SIZE_MB="$LOG_MAX_SIZE_MB" \
    -v "$LOG_DIR_HOST/indicator:/app/logs" \
    --log-driver json-file \
    --log-opt max-size=50m \
    --log-opt max-file=5 \
    --restart always \
    assessment-indicator:latest

echo "[启动] 评估分析服务 (10255)..."
docker run -d --name assessment-evaluation \
    --network "$NET_NAME" \
    -p 10255:10255 \
    -e LOG_ENV="$LOG_ENV" \
    -e LOG_LEVEL="$LOG_LEVEL" \
    -e LOG_DIR="/app/logs" \
    -e LOG_RETENTION_DAYS="$LOG_RETENTION_DAYS" \
    -e LOG_MAX_SIZE_MB="$LOG_MAX_SIZE_MB" \
    -v "$DATA_DIR/evaluation:/app/data" \
    -v "$LOG_DIR_HOST/evaluation:/app/logs" \
    --log-driver json-file \
    --log-opt max-size=50m \
    --log-opt max-file=5 \
    --restart always \
    assessment-evaluation:latest

echo "[启动] 本体模型服务 (10256)..."
docker run -d --name assessment-ontology \
    --network "$NET_NAME" \
    -p 10256:10256 \
    -e LOG_ENV="$LOG_ENV" \
    -e LOG_LEVEL="$LOG_LEVEL" \
    -e LOG_DIR="/app/logs" \
    -e LOG_RETENTION_DAYS="$LOG_RETENTION_DAYS" \
    -e LOG_MAX_SIZE_MB="$LOG_MAX_SIZE_MB" \
    -v "$DATA_DIR/ontology:/app/data" \
    -v "$LOG_DIR_HOST/ontology:/app/logs" \
    --log-driver json-file \
    --log-opt max-size=50m \
    --log-opt max-file=5 \
    --restart always \
    assessment-ontology:latest

echo "[启动] 态势图服务 (10257)..."
docker run -d --name assessment-situation \
    --network "$NET_NAME" \
    -p 10257:10257 \
    -e ADMIN_SERVICE_URL="http://assessment-admin:10258" \
    -e QA_SERVICE_URL="http://assessment-qa:10253" \
    -e KNOWLEDGE_SERVICE_URL="http://assessment-knowledge:10252" \
    -e INDICATOR_SERVICE_URL="http://assessment-indicator:10254" \
    -e SITUATION_SKILL_DB="/app/data/situation_skills.sqlite3" \
    -e SITUATION_SKILL_MD_OVERRIDE_DIR="/app/data/situation-skill-markdown-overrides" \
    -e SITUATION_GENERATION_MODE="real" \
    -e SITUATION_ALLOW_DATA_FALLBACK="true" \
    -e SITUATION_DATA_ROW_LIMIT="200" \
    -e SITUATION_AUTO_DATASET_LIMIT="2" \
    -e SITUATION_STREAM_REPLAY_TTL="300" \
    -e SITUATION_MAX_INFLIGHT="${SITUATION_MAX_INFLIGHT:-8}" \
    -e SITUATION_MAX_CONCURRENT="${SITUATION_MAX_CONCURRENT:-2}" \
    -e SITUATION_MAX_PER_USER="${SITUATION_MAX_PER_USER:-2}" \
    -e SITUATION_GENERATION_TIMEOUT="${SITUATION_GENERATION_TIMEOUT:-240}" \
    -e SITUATION_LLM_EVIDENCE_ROWS="${SITUATION_LLM_EVIDENCE_ROWS:-0}" \
    -e INTERNAL_SERVICE_TOKEN="$INTERNAL_SERVICE_TOKEN" \
    -e LLM_MAX_TOKENS="24000" \
    -e LOG_ENV="$LOG_ENV" \
    -e LOG_LEVEL="$LOG_LEVEL" \
    -e LOG_DIR="/app/logs" \
    -e LOG_RETENTION_DAYS="$LOG_RETENTION_DAYS" \
    -e LOG_MAX_SIZE_MB="$LOG_MAX_SIZE_MB" \
    -v "$DATA_DIR/situation:/app/data" \
    -v "$LOG_DIR_HOST/situation:/app/logs" \
    --log-driver json-file \
    --log-opt max-size=50m \
    --log-opt max-file=5 \
    --restart always \
    assessment-situation:latest

# ─── 7. Java 服务 (需要 MySQL 环境变量) ───
echo ""
echo "========================================"
echo "[3/9] 启动 Java 服务..."
echo "========================================"

echo "[启动] 基础管理服务 (10258)..."
docker run -d --name assessment-admin \
    --network "$NET_NAME" \
    -p 10258:10258 \
    -v drivers-data:/app/drivers \
    -e MYSQL_HOST="$MYSQL_HOST" \
    -e MYSQL_PORT="$MYSQL_PORT" \
    -e MYSQL_DATABASE="$MYSQL_DATABASE" \
    -e MYSQL_USER="$MYSQL_USER" \
    -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
    -e DB_TYPE="$DB_TYPE" \
    -e SPRING_PROFILES_ACTIVE="$LOG_ENV" \
    -e INTERNAL_SERVICE_TOKEN="$INTERNAL_SERVICE_TOKEN" \
    -e LOG_PATH="/app/logs" \
    -e LOG_LEVEL="$LOG_LEVEL" \
    -v "$LOG_DIR_HOST/admin:/app/logs" \
    --log-driver json-file \
    --log-opt max-size=50m \
    --log-opt max-file=5 \
    --restart always \
    assessment-admin:latest

# ─── 9. 等待管理服务就绪后启动前端 ───
echo ""
echo "========================================"
echo "[4/9] 等待管理服务就绪..."
echo "========================================"
for i in $(seq 1 90); do
    if curl -s http://127.0.0.1:10258/actuator/health >/dev/null 2>&1; then
        echo "  管理服务已就绪 (${i}s)"
        break
    fi
    if [ $i -eq 90 ]; then
        echo "  WARNING: 管理服务超时, 前端启动可能失败"
    fi
    sleep 1
done

echo "[启动] 前端界面 (10086)..."
docker run -d --name assessment-frontend \
    --network "$NET_NAME" \
    -p 10086:80 \
    --log-driver json-file \
    --log-opt max-size=20m \
    --log-opt max-file=3 \
    --restart always \
    assessment-frontend:latest

# ─── 4. 真实容器与 HTTP 冒烟校验 ───
echo ""
echo "========================================"
echo "[5/9] 校验 QA 容器和 Skill 目录接口..."
echo "========================================"
EXPECTED_IMAGE_ID="$(docker image inspect assessment-qa:latest --format '{{.Id}}')"
ACTUAL_IMAGE_ID="$(docker inspect assessment-qa --format '{{.Image}}')"
if [ "$EXPECTED_IMAGE_ID" != "$ACTUAL_IMAGE_ID" ]; then
    echo "ERROR: QA 容器没有使用 assessment-qa:latest"
    echo "  expected=$EXPECTED_IMAGE_ID"
    echo "  actual=$ACTUAL_IMAGE_ID"
    exit 1
fi
docker exec assessment-qa test -s /app/config/skills/README.md

QA_READY=0
for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:10253/health >/dev/null 2>&1; then
        QA_READY=1
        echo "  QA 健康检查通过 (${i}s)"
        break
    fi
    sleep 1
done
if [ "$QA_READY" -ne 1 ]; then
    echo "ERROR: QA 服务未通过健康检查"
    docker logs --tail 100 assessment-qa
    exit 1
fi

SKILL_RESPONSE="$(curl -fsS http://127.0.0.1:10253/evaluation/skills)"
if ! echo "$SKILL_RESPONSE" | grep -Eq '"builtInTotal"[[:space:]]*:[[:space:]]*30'; then
    echo "ERROR: Skill 目录接口未返回 30 个内置 Skill"
    echo "$SKILL_RESPONSE"
    exit 1
fi
echo "  Skill 目录接口校验通过: 30 个内置 Skill"

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
echo "  共启动 8 个服务"
echo "========================================"
