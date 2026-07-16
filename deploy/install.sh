#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

BASE_DIR="/opt/intelligent-assessment"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "========================================"
echo "智能评估系统 - CentOS 7.9 离线安装脚本"
echo "========================================"
echo ""

if [[ $EUID -ne 0 ]]; then
   log_error "请使用 root 权限运行此脚本"
   exit 1
fi

mkdir -p "$BASE_DIR"

# ---------- Step 1: 检查 Python 3.11 ----------
log_info "Step 1/5: 检查 Python 环境..."
PYTHON_CMD=""
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3 &> /dev/null; then
    PY_VER=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
    if [[ "$PY_VER" > "3.7" ]]; then
        PYTHON_CMD="python3"
    fi
fi

if [[ -z "$PYTHON_CMD" ]]; then
    log_error "未找到 Python 3.8+，请先安装 Python 3.11"
    echo ""
    echo "CentOS 7.9 安装 Python 3.11 方法:"
    echo "  1. 从源码编译:"
    echo "     yum install -y gcc openssl-devel bzip2-devel libffi-devel"
    echo "     cd /tmp && wget https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz"
    echo "     tar xzf Python-3.11.9.tgz && cd Python-3.11.9"
    echo "     ./configure --enable-optimizations && make -j4 && make install"
    echo ""
    echo "  2. 或使用预编译包 (请将此文件提前放入 deploy/python311-offline/):"
    echo "     如果 deploy/python311-offline/ 目录存在,脚本将自动安装"
    exit 1
fi

log_info "使用 Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# ---------- Step 2: 安装 Python 离线依赖 ----------
log_info "Step 2/5: 安装 Python 依赖包..."

$PYTHON_CMD -m pip install --no-index --find-links="$DEPLOY_DIR/offline-deps/python" \
    fastapi uvicorn pydantic python-multipart 2>/dev/null || {
    log_warn "离线安装 pip 包失败，尝试在线安装..."
    $PYTHON_CMD -m pip install fastapi uvicorn pydantic python-multipart
}

log_info "Python 依赖安装完成"

# ---------- Step 3: 部署前端 ----------
log_info "Step 3/5: 部署前端静态文件..."
mkdir -p "$BASE_DIR/frontend-dist"
cp -r "$DEPLOY_DIR/frontend-dist/"* "$BASE_DIR/frontend-dist/"
log_info "前端文件已复制到 $BASE_DIR/frontend-dist/"

# ---------- Step 4: 部署 Python 服务 ----------
log_info "Step 4/5: 部署 Python 服务..."

SERVICES=(
    "knowledge-service:10252"
    "qa-service:10253"
    "indicator-service:10254"
    "evaluation-service:10255"
    "ontology-service:10256"
    "solution-evaluation-service:10259"
)

for svc_info in "${SERVICES[@]}"; do
    IFS=':' read -r svc_name svc_port <<< "$svc_info"
    mkdir -p "$BASE_DIR/python/$svc_name"
    cp "$DEPLOY_DIR/python/$svc_name/main.py" "$BASE_DIR/python/$svc_name/"
    cp "$DEPLOY_DIR/python/$svc_name/requirements.txt" "$BASE_DIR/python/$svc_name/" 2>/dev/null || true
    if [[ -d "$DEPLOY_DIR/python/$svc_name/config" ]]; then
        cp -r "$DEPLOY_DIR/python/$svc_name/config" "$BASE_DIR/python/$svc_name/"
    fi
    log_info "  $svc_name -> $BASE_DIR/python/$svc_name/ (端口 $svc_port)"
done

# ---------- Step 5: 创建启动/停止脚本 ----------
log_info "Step 5/5: 创建服务管理脚本..."

cat > "$BASE_DIR/start.sh" << 'STARTSCRIPT'
#!/bin/bash
BASE_DIR="/opt/intelligent-assessment"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

PYTHON_CMD=""
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
fi

echo "智能评估系统 - 启动所有服务..."
echo ""

echo "[启动] 知识库服务 (10252)..."
nohup $PYTHON_CMD -m uvicorn main:app --host 0.0.0.0 --port 10252 \
    > "$LOG_DIR/knowledge.log" 2>&1 &
echo $! > "$BASE_DIR/pids/knowledge.pid"

echo "[启动] 智能问答服务 (10253)..."
nohup $PYTHON_CMD -m uvicorn main:app --host 0.0.0.0 --port 10253 \
    > "$LOG_DIR/qa.log" 2>&1 &
echo $! > "$BASE_DIR/pids/qa.pid"

echo "[启动] 指标分析服务 (10254)..."
nohup $PYTHON_CMD -m uvicorn main:app --host 0.0.0.0 --port 10254 \
    > "$LOG_DIR/indicator.log" 2>&1 &
echo $! > "$BASE_DIR/pids/indicator.pid"

echo "[启动] 评估分析服务 (10255)..."
nohup $PYTHON_CMD -m uvicorn main:app --host 0.0.0.0 --port 10255 \
    > "$LOG_DIR/evaluation.log" 2>&1 &
echo $! > "$BASE_DIR/pids/evaluation.pid"

echo "[启动] 本体模型服务 (10256)..."
nohup $PYTHON_CMD -m uvicorn main:app --host 0.0.0.0 --port 10256 \
    > "$LOG_DIR/ontology.log" 2>&1 &
echo $! > "$BASE_DIR/pids/ontology.pid"

echo "[启动] 题解评估服务 (10259)..."
nohup $PYTHON_CMD -m uvicorn main:app --host 0.0.0.0 --port 10259 \
    > "$LOG_DIR/solution-evaluation.log" 2>&1 &
echo $! > "$BASE_DIR/pids/solution-evaluation.pid"

echo ""
echo "前端可通过 nginx 或 Python http.server 服务:"
echo "  cd $BASE_DIR/frontend-dist && nohup $PYTHON_CMD -m http.server 3000 > $LOG_DIR/frontend.log 2>&1 &"
echo ""
echo "========================================"
echo "服务状态检查:"
echo "========================================"
sleep 3

check_port() {
    local port=$1
    local name=$2
    if ss -tlnp 2>/dev/null | grep -q ":$port " || netstat -tlnp 2>/dev/null | grep -q ":$port "; then
        echo "  [✓] $name (端口 $port) - 运行中"
    else
        echo "  [✗] $name (端口 $port) - 未启动"
    fi
}

check_port 10252 "知识库服务"
check_port 10253 "智能问答服务"
check_port 10254 "指标分析服务"
check_port 10255 "评估分析服务"
check_port 10256 "本体模型服务"
check_port 10259 "评估分析服务(多Agent)"
check_port 3000 "前端服务"

echo ""
echo "访问地址: http://<服务器IP>:3000"
echo "========================================"
STARTSCRIPT

cat > "$BASE_DIR/stop.sh" << 'STOPSSCRIPT'
#!/bin/bash
echo "智能评估系统 - 停止所有服务..."

BASE_DIR="/opt/intelligent-assessment"
PIDS_DIR="$BASE_DIR/pids"

stop_service() {
    local name=$1
    local port=$2
    local pid_file="$PIDS_DIR/$name.pid"

    if [[ -f "$pid_file" ]]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo "[停止] $name (PID: $pid)"
            rm -f "$pid_file"
        else
            echo "[跳过] $name (进程不存在)"
            rm -f "$pid_file"
        fi
    fi

    local pids=$(pgrep -f "uvicorn main:app.*--port $port" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "[清理] 强制停止端口 $port 上的残留进程..."
        kill $pids 2>/dev/null || true
    fi
}

stop_service "knowledge" "10252"
stop_service "qa" "10253"
stop_service "indicator" "10254"
stop_service "evaluation" "10255"
stop_service "ontology" "10256"
stop_service "solution-evaluation" "10259"

pkill -f "http.server 3000" 2>/dev/null && echo "[停止] 前端服务" || true

echo ""
echo "所有服务已停止"
STOPSSCRIPT

cat > "$BASE_DIR/status.sh" << 'STATUSSCRIPT'
#!/bin/bash
echo "========================================"
echo "智能评估系统 - 服务状态"
echo "========================================"

check_port() {
    local port=$1
    local name=$2
    if ss -tlnp 2>/dev/null | grep -q ":$port " || netstat -tlnp 2>/dev/null | grep -q ":$port "; then
        echo -e "  \033[0;32m[✓]\033[0m $name (端口 $port) - 运行中"
    else
        echo -e "  \033[0;31m[✗]\033[0m $name (端口 $port) - 未启动"
    fi
}

check_port 3000 "前端界面"
check_port 10252 "知识库服务"
check_port 10253 "智能问答服务"
check_port 10254 "指标分析服务"
check_port 10255 "评估分析服务"
check_port 10256 "本体模型服务"
check_port 10259 "评估分析服务(多Agent)"

echo "========================================"
STATUSSCRIPT

mkdir -p "$BASE_DIR/pids" "$BASE_DIR/logs"
chmod +x "$BASE_DIR/start.sh" "$BASE_DIR/stop.sh" "$BASE_DIR/status.sh"

# ---------- 配置防火墙 ----------
log_info "配置防火墙规则..."
if systemctl is-active --quiet firewalld 2>/dev/null; then
    for port in 3000 10252 10253 10254 10255 10256 10259; do
        firewall-cmd --permanent --add-port=$port/tcp 2>/dev/null || true
    done
    firewall-cmd --reload 2>/dev/null || true
    log_info "防火墙端口已开放"
else
    log_warn "firewalld 未运行，如使用 iptables 请手动配置"
fi

# ---------- 完成 ----------
echo ""
echo "========================================"
echo -e "${GREEN}离线安装完成!${NC}"
echo "========================================"
echo ""
echo "目录结构:"
echo "  $BASE_DIR/"
echo "  ├── frontend-dist/    # 前端静态文件"
echo "  ├── python/           # Python 服务"
echo "  ├── pids/             # 进程 PID 文件"
echo "  ├── logs/             # 服务日志"
echo "  ├── start.sh          # 启动所有服务"
echo "  ├── stop.sh           # 停止所有服务"
echo "  └── status.sh         # 查看服务状态"
echo ""
echo "启动服务:"
echo "  cd $BASE_DIR && bash start.sh"
echo ""
echo "停止服务:"
echo "  cd $BASE_DIR && bash stop.sh"
echo ""
echo "查看状态:"
echo "  cd $BASE_DIR && bash status.sh"
echo ""
echo "访问地址: http://$(hostname -I | awk '{print $1}'):3000"
echo "========================================"
