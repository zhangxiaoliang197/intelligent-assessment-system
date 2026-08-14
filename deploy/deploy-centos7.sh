#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
IMAGES_DIR="$PROJECT_DIR/docker-images"
DEPLOY_TARGET="/opt/intelligent-assessment"

echo "========================================"
echo "智能评估系统 - CentOS 7.9 离线部署脚本"
echo "========================================"
echo ""

if [[ $EUID -ne 0 ]]; then
   log_error "请使用 root 权限运行此脚本"
   exit 1
fi

# ---------- 检查 Docker ----------
log_info "Step 1/4: 检查 Docker 环境..."

if ! command -v docker &> /dev/null; then
    log_error "未安装 Docker, 请先安装 Docker CE"
    echo ""
    echo "CentOS 7.9 安装 Docker CE:"
    echo "  yum install -y yum-utils"
    echo "  yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo"
    echo "  yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin"
    echo "  systemctl enable docker && systemctl start docker"
    exit 1
fi

if ! systemctl is-active --quiet docker 2>/dev/null; then
    log_info "启动 Docker 服务..."
    systemctl start docker
fi

DOCKER_VER=$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',' || echo "unknown")
log_info "Docker 版本: $DOCKER_VER"

# ---------- 加载镜像 ----------
log_info "Step 2/4: 加载 Docker 镜像..."

if [[ ! -d "$IMAGES_DIR" ]]; then
    log_error "未找到镜像目录: $IMAGES_DIR"
    exit 1
fi

IMAGE_COUNT=0
for tarfile in "$IMAGES_DIR"/*.tar; do
    if [[ -f "$tarfile" ]]; then
        BASENAME=$(basename "$tarfile" .tar)
        log_info "  加载: $BASENAME"
        docker load -i "$tarfile" || { log_error "加载 $BASENAME 失败"; exit 1; }
        IMAGE_COUNT=$((IMAGE_COUNT + 1))
    fi
done

if [[ $IMAGE_COUNT -eq 0 ]]; then
    log_error "未找到任何镜像文件 (.tar) 在 $IMAGES_DIR/"
    exit 1
fi

log_info "共加载 $IMAGE_COUNT 个镜像"

# 不允许把缺少内置 Skill 目录的 QA 镜像带入运行阶段。
log_info "校验 assessment-qa:latest 内置 Skill 目录..."
docker run --rm --entrypoint python assessment-qa:latest \
    -c "from agents.skill_catalog import load_catalog; catalog=load_catalog(); assert len(catalog['skills']) == 30; print('Skill catalog OK:', len(catalog['skills']))"
log_info "校验 assessment-situation:latest 内置 Skill 测试..."
docker run --rm --entrypoint python assessment-situation:latest \
    -m unittest discover -s tests -p 'test_*.py' -v

# ---------- 部署项目 ----------
log_info "Step 3/4: 部署项目文件..."

mkdir -p "$DEPLOY_TARGET"

MYSQL_HOST="${MYSQL_HOST:-}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATABASE="${MYSQL_DATABASE:-assessment}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"
DB_TYPE="${DB_TYPE:-mysql}"
INTERNAL_SERVICE_TOKEN="${INTERNAL_SERVICE_TOKEN:-}"
ADMIN_API_TOKEN="${ADMIN_API_TOKEN:-}"
ADMIN_UI_PASSWORD="${ADMIN_UI_PASSWORD:-}"
SITUATION_LLM_ALLOWED_HOSTS="${SITUATION_LLM_ALLOWED_HOSTS:-api.deepseek.com,localhost,127.0.0.1,::1}"

# ─── 日志环境变量（可被外部环境变量覆盖）───
LOG_ENV="${LOG_ENV:-prod}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-14}"
LOG_MAX_SIZE_MB="${LOG_MAX_SIZE_MB:-100}"

# 校验：MYSQL_HOST 必须显式配置（元数据库在远程，无默认值）
if [ -z "$MYSQL_HOST" ]; then
    log_error "MYSQL_HOST 未配置。请通过环境变量指定元数据库地址。"
    echo "  示例: MYSQL_HOST=192.168.1.100 MYSQL_PASSWORD=xxx bash deploy-centos7.sh"
    exit 1
fi
if [ ${#INTERNAL_SERVICE_TOKEN} -lt 24 ] || [ "$INTERNAL_SERVICE_TOKEN" = "local-development-token" ]; then
    log_error "INTERNAL_SERVICE_TOKEN 必须显式配置为至少 24 位随机值"
    exit 1
fi
if [ ${#ADMIN_API_TOKEN} -lt 24 ]; then
    log_error "ADMIN_API_TOKEN 必须显式配置为至少 24 位随机值"
    exit 1
fi
if [ ${#ADMIN_UI_PASSWORD} -lt 16 ] || [ "$ADMIN_UI_PASSWORD" = "$ADMIN_API_TOKEN" ] || [ "$ADMIN_UI_PASSWORD" = "$INTERNAL_SERVICE_TOKEN" ]; then
    log_error "ADMIN_UI_PASSWORD 必须为至少 16 位且与服务凭据不同的随机值"
    exit 1
fi
case "$ADMIN_UI_PASSWORD" in
    *'$'*) log_error "ADMIN_UI_PASSWORD 不能包含美元符号"; exit 1 ;;
esac

cat > "$DEPLOY_TARGET/docker-compose.yml" << DOCKERCOMPOSE
services:
  # ─── Qdrant 向量数据库 ───
  qdrant:
    image: qdrant/qdrant:latest
    container_name: assessment-qdrant
    ports:
      - "6333:6333"
    restart: always
    volumes:
      - "$DEPLOY_TARGET/data/qdrant:/qdrant/storage"
    networks:
      - assessment-net

  frontend:
    image: assessment-frontend:latest
    container_name: assessment-frontend
    ports:
      - "10086:80"
    restart: always
    environment:
      - ADMIN_API_TOKEN=$ADMIN_API_TOKEN
      - ADMIN_UI_PASSWORD=$ADMIN_UI_PASSWORD
    networks:
      - assessment-net
    logging:
      driver: json-file
      options:
        max-size: "20m"
        max-file: "3"

  knowledge-service:
    image: assessment-knowledge:latest
    container_name: assessment-knowledge
    ports:
      - "10252:10252"
    restart: always
    environment:
      - QDRANT_URL=http://assessment-qdrant:6333
      - LOG_ENV=\${LOG_ENV:-prod}
      - LOG_LEVEL=\${LOG_LEVEL:-INFO}
      - LOG_DIR=/app/logs
      - LOG_RETENTION_DAYS=\${LOG_RETENTION_DAYS:-14}
      - LOG_MAX_SIZE_MB=\${LOG_MAX_SIZE_MB:-100}
    volumes:
      - "$DEPLOY_TARGET/data/knowledge:/app/data"
      - "$DEPLOY_TARGET/logs/knowledge:/app/logs"
    networks:
      - assessment-net
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  qa-service:
    image: assessment-qa:latest
    container_name: assessment-qa
    ports:
      - "10253:10253"
    restart: always
    environment:
      - ADMIN_SERVICE_URL=http://assessment-admin:10258
      - KNOWLEDGE_SERVICE_URL=http://assessment-knowledge:10252
      - ONTOLOGY_SERVICE_URL=http://assessment-ontology:10256
      - INTERNAL_SERVICE_TOKEN=$INTERNAL_SERVICE_TOKEN
      - EVALUATION_SKILLS_DIR=/app/config/skills
      - LOG_ENV=\${LOG_ENV:-prod}
      - LOG_LEVEL=\${LOG_LEVEL:-INFO}
      - LOG_DIR=/app/logs
      - LOG_RETENTION_DAYS=\${LOG_RETENTION_DAYS:-14}
      - LOG_MAX_SIZE_MB=\${LOG_MAX_SIZE_MB:-100}
      - LOG_ROTATION_MODE=size
    volumes:
      - "$DEPLOY_TARGET/data/qa:/app/data"
      - "$DEPLOY_TARGET/data/config/skills:/app/config/skills:ro"
      - "$DEPLOY_TARGET/logs/qa:/app/logs"
    networks:
      - assessment-net
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  indicator-service:
    image: assessment-indicator:latest
    container_name: assessment-indicator
    ports:
      - "10254:10254"
    restart: always
    environment:
      - QA_SERVICE_URL=http://assessment-qa:10253
      - ADMIN_SERVICE_URL=http://assessment-admin:10258
      - KNOWLEDGE_SERVICE_URL=http://assessment-knowledge:10252
      - EVALUATION_API_URL=http://assessment-qa:10253
      - ONTOLOGY_SERVICE_URL=http://assessment-ontology:10256
      - INTERNAL_SERVICE_TOKEN=$INTERNAL_SERVICE_TOKEN
      - LOG_ENV=\${LOG_ENV:-prod}
      - LOG_LEVEL=\${LOG_LEVEL:-INFO}
      - LOG_DIR=/app/logs
      - LOG_RETENTION_DAYS=\${LOG_RETENTION_DAYS:-14}
      - LOG_MAX_SIZE_MB=\${LOG_MAX_SIZE_MB:-100}
    volumes:
      - "$DEPLOY_TARGET/data/indicator:/app/data"
      - "$DEPLOY_TARGET/logs/indicator:/app/logs"
    networks:
      - assessment-net
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  evaluation-service:
    image: assessment-evaluation:latest
    container_name: assessment-evaluation
    ports:
      - "10255:10255"
    restart: always
    environment:
      - LOG_ENV=\${LOG_ENV:-prod}
      - LOG_LEVEL=\${LOG_LEVEL:-INFO}
      - LOG_DIR=/app/logs
      - LOG_RETENTION_DAYS=\${LOG_RETENTION_DAYS:-14}
      - LOG_MAX_SIZE_MB=\${LOG_MAX_SIZE_MB:-100}
    volumes:
      - "$DEPLOY_TARGET/data/evaluation:/app/data"
      - "$DEPLOY_TARGET/logs/evaluation:/app/logs"
    networks:
      - assessment-net
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  ontology-service:
    image: assessment-ontology:latest
    container_name: assessment-ontology
    ports:
      - "10256:10256"
    restart: always
    environment:
      - ADMIN_SERVICE_URL=http://assessment-admin:10258
      - INTERNAL_SERVICE_TOKEN=$INTERNAL_SERVICE_TOKEN
      - LOG_ENV=\${LOG_ENV:-prod}
      - LOG_LEVEL=\${LOG_LEVEL:-INFO}
      - LOG_DIR=/app/logs
      - LOG_RETENTION_DAYS=\${LOG_RETENTION_DAYS:-14}
      - LOG_MAX_SIZE_MB=\${LOG_MAX_SIZE_MB:-100}
    volumes:
      - "$DEPLOY_TARGET/data/ontology:/app/data"
      - "$DEPLOY_TARGET/logs/ontology:/app/logs"
    networks:
      - assessment-net
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  situation-service:
    image: assessment-situation:latest
    container_name: assessment-situation
    ports:
      - "127.0.0.1:10257:10257"
    restart: always
    environment:
      - ADMIN_SERVICE_URL=http://assessment-admin:10258
      - QA_SERVICE_URL=http://assessment-qa:10253
      - KNOWLEDGE_SERVICE_URL=http://assessment-knowledge:10252
      - INDICATOR_SERVICE_URL=http://assessment-indicator:10254
      - SITUATION_GENERATION_MODE=real
      - SITUATION_ALLOW_DATA_FALLBACK=true
      - SITUATION_MAX_INFLIGHT=8
      - SITUATION_MAX_CONCURRENT=2
      - SITUATION_MAX_PER_USER=2
      - SITUATION_GENERATION_TIMEOUT=240
      - SITUATION_LLM_EVIDENCE_ROWS=0
      - SITUATION_LLM_ALLOWED_HOSTS=$SITUATION_LLM_ALLOWED_HOSTS
      - SITUATION_CORS_ORIGINS=${SITUATION_CORS_ORIGINS:-http://localhost:10086,http://127.0.0.1:10086}
      - INTERNAL_SERVICE_TOKEN=$INTERNAL_SERVICE_TOKEN
      - SITUATION_SKILL_DB=/app/data/situation_skills.sqlite3
      - SITUATION_SKILL_MD_OVERRIDE_DIR=/app/data/situation-skill-markdown-overrides
      - LOG_ENV=prod
      - LOG_DIR=/app/logs
    volumes:
      - "$DEPLOY_TARGET/data/situation:/app/data"
      - "$DEPLOY_TARGET/logs/situation:/app/logs"
    networks:
      - assessment-net
    depends_on:
      - admin-service
    healthcheck:
      test: ["CMD", "python", "-c", "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:10257/situation/health',timeout=3)); h=d.get('data',{}); assert d.get('success') and h.get('skills',0)>=30 and h.get('skillStorage')=='healthy'"]
      interval: 30s
      timeout: 5s
      start_period: 20s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  admin-service:
    image: assessment-admin:latest
    container_name: assessment-admin
    ports:
      - "127.0.0.1:10258:10258"
    restart: always
    environment:
      - MYSQL_HOST=$MYSQL_HOST
      - MYSQL_PORT=$MYSQL_PORT
      - MYSQL_DATABASE=$MYSQL_DATABASE
      - MYSQL_USER=$MYSQL_USER
      - MYSQL_PASSWORD=$MYSQL_PASSWORD
      - DB_TYPE=$DB_TYPE
      - INTERNAL_SERVICE_TOKEN=$INTERNAL_SERVICE_TOKEN
      - ADMIN_API_TOKEN=$ADMIN_API_TOKEN
      - SPRING_PROFILES_ACTIVE=\${LOG_ENV:-prod}
      - LOG_PATH=/app/logs
      - LOG_LEVEL=\${LOG_LEVEL:-INFO}
    volumes:
      - drivers-data:/app/drivers
      - "$DEPLOY_TARGET/logs/admin:/app/logs"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://127.0.0.1:10258/actuator/health"]
      interval: 30s
      timeout: 5s
      start_period: 40s
      retries: 3
    networks:
      - assessment-net
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

networks:
  assessment-net:
    driver: bridge

volumes:
  drivers-data:
DOCKERCOMPOSE

mkdir -p "$DEPLOY_TARGET/data"/{knowledge,qa,ontology,evaluation,indicator,situation,qdrant,config}
mkdir -p "$DEPLOY_TARGET/logs"/{knowledge,qa,indicator,evaluation,ontology,situation,admin}

# drivers 使用命名卷 drivers-data，首次启动时自动从镜像内 /app/drivers 复制驱动。
# 如需补充 Oracle/达梦等驱动，请通过管理后台「驱动管理」页面上传，或重新构建镜像。

cp "$DEPLOY_DIR/queries.json" "$DEPLOY_TARGET/data/config/queries.json" 2>/dev/null || echo '[]' > "$DEPLOY_TARGET/data/config/queries.json"

# 导出经过镜像构建闸门校验的 Markdown 目录，运行时以只读目录挂载，
# 避免历史遗留的 /app/config 整目录挂载遮蔽镜像内容。
SKILLS_DIR="$DEPLOY_TARGET/data/config/skills"
SKILLS_TMP_DIR="$DEPLOY_TARGET/data/config/skills.tmp.$$"
CATALOG_EXPORT_CONTAINER="assessment-qa-catalog-export-$$"
docker rm -f "$CATALOG_EXPORT_CONTAINER" >/dev/null 2>&1 || true
docker create --name "$CATALOG_EXPORT_CONTAINER" assessment-qa:latest >/dev/null
rm -rf "$SKILLS_TMP_DIR"
mkdir -p "$SKILLS_TMP_DIR"
if ! docker cp "$CATALOG_EXPORT_CONTAINER:/app/config/skills/." "$SKILLS_TMP_DIR"; then
    docker rm -f "$CATALOG_EXPORT_CONTAINER" >/dev/null 2>&1 || true
    rm -rf "$SKILLS_TMP_DIR"
    log_error "无法从 assessment-qa:latest 导出 /app/config/skills"
    exit 1
fi
docker rm "$CATALOG_EXPORT_CONTAINER" >/dev/null
rm -rf "$SKILLS_DIR"
mv "$SKILLS_TMP_DIR" "$SKILLS_DIR"
test -s "$SKILLS_DIR/README.md"
test "$(find "$SKILLS_DIR" -mindepth 2 -maxdepth 2 -name SKILL.md -type f | wc -l)" -eq 30

log_info "docker-compose.yml 已部署"

# ---------- 创建管理脚本 ----------
log_info "Step 4/4: 创建服务管理脚本..."

cat > "$DEPLOY_TARGET/start.sh" << 'STARTSCRIPT'
#!/bin/bash
set -euo pipefail

echo "智能评估系统 - 启动所有服务..."
cd /opt/intelligent-assessment

# docker-compose.yml 已写入经部署期强校验的凭据值。

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "ERROR: 未找到 docker compose 或 docker-compose"
    exit 1
fi

# 清理可能由旧版 docker run 脚本创建的同名容器。所有持久数据均在
# /opt/intelligent-assessment/data 下，重建容器不会删除业务数据。
SERVICE_CONTAINERS=(
    assessment-frontend
    assessment-admin
    assessment-situation
    assessment-ontology
    assessment-evaluation
    assessment-indicator
    assessment-qa
    assessment-knowledge
    assessment-qdrant
)
for container_name in "${SERVICE_CONTAINERS[@]}"; do
    if docker ps -a --format '{{.Names}}' | grep -qx "$container_name"; then
        echo "替换旧容器: $container_name"
        docker rm -f "$container_name" >/dev/null
    fi
done

"${COMPOSE[@]}" up -d --force-recreate
echo ""
echo "校验运行容器使用的新 QA 镜像..."
EXPECTED_IMAGE_ID="$(docker image inspect assessment-qa:latest --format '{{.Id}}')"
ACTUAL_IMAGE_ID="$(docker inspect assessment-qa --format '{{.Image}}')"
if [[ "$EXPECTED_IMAGE_ID" != "$ACTUAL_IMAGE_ID" ]]; then
    echo "ERROR: QA 容器仍未使用 assessment-qa:latest"
    echo "  expected=$EXPECTED_IMAGE_ID"
    echo "  actual=$ACTUAL_IMAGE_ID"
    exit 1
fi
docker exec assessment-qa test -s /app/config/skills/README.md

QA_READY=0
for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:10253/health >/dev/null 2>&1; then
        QA_READY=1
        echo "QA 健康检查通过 (${i}s)"
        break
    fi
    sleep 1
done
if [[ "$QA_READY" -ne 1 ]]; then
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
echo "Skill 目录接口校验通过: 30 个内置 Skill"

SITUATION_READY=0
for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:10257/situation/health >/dev/null 2>&1; then
        SITUATION_READY=1
        echo "态势服务健康检查通过 (${i}s)"
        break
    fi
    sleep 1
done
if [[ "$SITUATION_READY" -ne 1 ]]; then
    echo "ERROR: 态势服务未通过健康检查"
    docker logs --tail 100 assessment-situation
    exit 1
fi
SITUATION_SKILLS="$(curl -fsS http://127.0.0.1:10257/situation/skills?limit=100)"
if ! echo "$SITUATION_SKILLS" | grep -Eq '"catalogTotal"[[:space:]]*:[[:space:]]*30'; then
    echo "ERROR: 态势 Skill 目录未返回 30 个 Skill"
    exit 1
fi
echo "态势服务校验通过: 30 个内置 Skill"

echo ""
echo "服务状态:"
"${COMPOSE[@]}" ps
echo ""
echo "访问地址: http://$(hostname -I | awk '{print $1}'):10086"
STARTSCRIPT

cat > "$DEPLOY_TARGET/stop.sh" << 'STOPSCRIPT'
#!/bin/bash
echo "智能评估系统 - 停止所有服务..."
cd /opt/intelligent-assessment
docker compose down
echo "所有服务已停止"
STOPSCRIPT

cat > "$DEPLOY_TARGET/status.sh" << 'STATUS'
#!/bin/bash
echo "========================================"
echo "智能评估系统 - 服务状态"
echo "========================================"
cd /opt/intelligent-assessment
docker compose ps
echo "========================================"
STATUS

cat > "$DEPLOY_TARGET/restart.sh" << 'RESTART'
#!/bin/bash
set -euo pipefail
echo "智能评估系统 - 以当前镜像重建所有服务..."
exec bash /opt/intelligent-assessment/start.sh
RESTART

chmod +x "$DEPLOY_TARGET"/*.sh

# ---------- 防火墙 ----------
if systemctl is-active --quiet firewalld 2>/dev/null; then
    log_info "配置防火墙..."
    for port in 10086 10252 10253 10254 10255 10256 6333; do
        firewall-cmd --permanent --add-port=$port/tcp 2>/dev/null || true
    done
    firewall-cmd --reload 2>/dev/null || true
fi

# ---------- 完成 ----------
echo ""
echo "========================================"
echo -e "${GREEN}部署完成!${NC}"
echo "========================================"
echo ""
echo "项目目录: $DEPLOY_TARGET"
echo ""
echo "启动服务: cd $DEPLOY_TARGET && bash start.sh"
echo "停止服务: cd $DEPLOY_TARGET && bash stop.sh"
echo "查看状态: cd $DEPLOY_TARGET && bash status.sh"
echo "重启服务: cd $DEPLOY_TARGET && bash restart.sh"
echo ""
echo "访问地址: http://$(hostname -I | awk '{print $1}'):10086"
echo "SECURITY: 生产环境必须在 10086 前配置 TLS，Basic Auth 禁止经明文 HTTP 跨网传输"
echo "========================================"
