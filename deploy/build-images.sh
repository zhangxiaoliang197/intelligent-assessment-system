#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGES_DIR="$PROJECT_DIR/docker-images"
VERSION="${VERSION:-$(date +%Y%m%d)}"
mkdir -p "$IMAGES_DIR"

echo "========================================"
echo "智能评估系统 - Docker 镜像构建脚本"
echo "版本: $VERSION"
echo "========================================"
echo ""

build_image() {
    local name=$1
    local dockerfile=$2
    echo "[构建] $name ..."
    docker build -t "assessment-$name:latest" \
        -f "$PROJECT_DIR/docker/Dockerfile.$dockerfile" \
        "$PROJECT_DIR"
    docker tag "assessment-$name:latest" "assessment-$name:$VERSION"
}

save_image() {
    local name=$1
    echo "[导出] assessment-$name:latest + :$VERSION -> $IMAGES_DIR/assessment-$name.tar"
    docker save -o "$IMAGES_DIR/assessment-$name.tar" \
        "assessment-$name:latest" "assessment-$name:$VERSION"
}

echo "=== 第0步: 构建前端产物 ==="
if [[ "${SKIP_FRONTEND_BUILD:-0}" == "1" ]]; then
    echo "[跳过] SKIP_FRONTEND_BUILD=1"
else
    # frontend Dockerfile 直接 COPY frontend/dist，必须先把最新源码构建成 dist
    ( cd "$PROJECT_DIR/frontend" && npm ci && npm run build )
fi

echo "=== 第1步: 构建前端 ==="
build_image "frontend" "frontend"
save_image "frontend"

echo ""
echo "=== 第2步: 构建 Python 服务 ==="
build_image "knowledge" "knowledge"
save_image "knowledge"

build_image "qa" "qa"
echo "[校验] assessment-qa:latest 内置 Skill 目录 ..."
docker run --rm --entrypoint python assessment-qa:latest \
    -c "from agents.skill_catalog import load_catalog; catalog=load_catalog(); assert len(catalog['skills']) == 30; print('Skill catalog OK:', len(catalog['skills']))"
save_image "qa"

build_image "indicator" "indicator"
save_image "indicator"

build_image "evaluation" "evaluation"
save_image "evaluation"

build_image "ontology" "ontology"
save_image "ontology"

build_image "ipage" "ipage"
echo "[校验] assessment-ipage:latest 单元测试 ..."
docker run --rm --entrypoint python assessment-ipage:latest \
    -m unittest discover -s tests -p 'test_*.py' -v
save_image "ipage"

echo ""
echo "=== 第3步: 构建 Java 服务 ==="
build_image "admin" "admin"
save_image "admin"

echo ""
echo "=== 第4步: 保存 Qdrant 镜像（离线内网必需） ==="
docker pull qdrant/qdrant:latest
docker save -o "$IMAGES_DIR/assessment-qdrant.tar" qdrant/qdrant:latest
echo "[导出] qdrant/qdrant:latest -> $IMAGES_DIR/assessment-qdrant.tar"

echo ""
echo "========================================"
echo "所有镜像构建完成!"
echo "========================================"
echo ""
echo "镜像文件位于: $IMAGES_DIR/"
ls -lh "$IMAGES_DIR/"
echo ""
echo "下一步: 将整个项目传输到 CentOS 7.9 服务器"
echo "  tar -czf assessment-deploy.tar.gz docker-images/ deploy/ docker-compose.yml"
echo "  scp assessment-deploy.tar.gz root@<服务器IP>:/opt/"
echo ""
echo "在服务器上执行:"
echo "  cd /opt && tar -xzf assessment-deploy.tar.gz"
echo "  bash deploy/deploy-centos7.sh"
