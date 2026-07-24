#!/bin/bash

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

# ---------- 部署项目 ----------
log_info "Step 3/4: 部署项目文件..."

mkdir -p "$DEPLOY_TARGET"

MYSQL_HOST="${MYSQL_HOST:-}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATABASE="${MYSQL_DATABASE:-assessment}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"
DB_TYPE="${DB_TYPE:-mysql}"

# 校验：MYSQL_HOST 必须显式配置（元数据库在远程，无默认值）
if [ -z "$MYSQL_HOST" ]; then
    log_error "MYSQL_HOST 未配置。请通过环境变量指定元数据库地址。"
    echo "  示例: MYSQL_HOST=192.168.1.100 MYSQL_PASSWORD=xxx bash deploy-centos7.sh"
    exit 1
fi

cat > "$DEPLOY_TARGET/docker-compose.yml" << DOCKERCOMPOSE
services:
  frontend:
    image: assessment-frontend:latest
    container_name: assessment-frontend
    ports:
      - "10086:80"
    restart: always
    networks:
      - assessment-net

  knowledge-service:
    image: assessment-knowledge:latest
    container_name: assessment-knowledge
    ports:
      - "10252:10252"
    restart: always
    volumes:
      - "$DEPLOY_TARGET/data/knowledge:/app/data"
    networks:
      - assessment-net

  qa-service:
    image: assessment-qa:latest
    container_name: assessment-qa
    ports:
      - "10253:10253"
    restart: always
    environment:
      - ADMIN_SERVICE_URL=http://assessment-admin:10258
      - KNOWLEDGE_SERVICE_URL=http://assessment-knowledge:10252
    volumes:
      - "$DEPLOY_TARGET/data/qa:/app/data"
    networks:
      - assessment-net

  indicator-service:
    image: assessment-indicator:latest
    container_name: assessment-indicator
    ports:
      - "10254:10254"
    restart: always
    environment:
      - QA_SERVICE_URL=http://assessment-qa:10253
      - ADMIN_SERVICE_URL=http://assessment-admin:10258
    volumes:
      - "$DEPLOY_TARGET/data/indicator:/app/data"
    networks:
      - assessment-net

  evaluation-service:
    image: assessment-evaluation:latest
    container_name: assessment-evaluation
    ports:
      - "10255:10255"
    restart: always
    volumes:
      - "$DEPLOY_TARGET/data/evaluation:/app/data"
    networks:
      - assessment-net

  ontology-service:
    image: assessment-ontology:latest
    container_name: assessment-ontology
    ports:
      - "10256:10256"
    restart: always
    volumes:
      - "$DEPLOY_TARGET/data/ontology:/app/data"
    networks:
      - assessment-net

  admin-service:
    image: assessment-admin:latest
    container_name: assessment-admin
    ports:
      - "10258:10258"
    restart: always
    environment:
      - MYSQL_HOST=$MYSQL_HOST
      - MYSQL_PORT=$MYSQL_PORT
      - MYSQL_DATABASE=$MYSQL_DATABASE
      - MYSQL_USER=$MYSQL_USER
      - MYSQL_PASSWORD=$MYSQL_PASSWORD
      - DB_TYPE=$DB_TYPE
    volumes:
      - drivers-data:/app/drivers
    networks:
      - assessment-net

networks:
  assessment-net:
    driver: bridge

volumes:
  drivers-data:
DOCKERCOMPOSE

mkdir -p "$DEPLOY_TARGET/data"/{knowledge,qa,ontology,evaluation,indicator,config}

# drivers 使用命名卷 drivers-data，首次启动时自动从镜像内 /app/drivers 复制驱动。
# 如需补充 Oracle/达梦等驱动，请通过管理后台「驱动管理」页面上传，或重新构建镜像。

cp "$DEPLOY_DIR/queries.json" "$DEPLOY_TARGET/data/config/queries.json" 2>/dev/null || echo '[]' > "$DEPLOY_TARGET/data/config/queries.json"

log_info "docker-compose.yml 已部署"

# ---------- 创建管理脚本 ----------
log_info "Step 4/4: 创建服务管理脚本..."

cat > "$DEPLOY_TARGET/start.sh" << 'STARTSCRIPT'
#!/bin/bash
echo "智能评估系统 - 启动所有服务..."
cd /opt/intelligent-assessment
docker compose up -d
echo ""
echo "等待服务就绪..."
sleep 5
echo ""
echo "服务状态:"
docker compose ps
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
echo "智能评估系统 - 重启所有服务..."
cd /opt/intelligent-assessment
docker compose restart
echo "服务已重启"
RESTART

chmod +x "$DEPLOY_TARGET"/*.sh

# ---------- 防火墙 ----------
if systemctl is-active --quiet firewalld 2>/dev/null; then
    log_info "配置防火墙..."
    for port in 10086 10252 10253 10254 10255 10256 10258; do
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
echo "========================================"
