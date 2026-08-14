#!/bin/bash
set -euo pipefail

# Replace only the QA container with the verified image from this hotfix.
# Existing knowledge/admin/frontend containers and all host data stay intact.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_TAR="${1:-$PROJECT_DIR/docker-images/assessment-qa.tar}"
BASE_DIR="${ASSESSMENT_BASE_DIR:-/opt/intelligent-assessment}"
DATA_DIR="$BASE_DIR/data"
NETWORK_NAME="${ASSESSMENT_NETWORK:-}"
QA_PORT="${QA_PORT:-10253}"
INTERNAL_SERVICE_TOKEN="${INTERNAL_SERVICE_TOKEN:-}"

if [ ${#INTERNAL_SERVICE_TOKEN} -lt 24 ] || [ "$INTERNAL_SERVICE_TOKEN" = "local-development-token" ]; then
    echo "ERROR: INTERNAL_SERVICE_TOKEN 必须显式配置为至少 24 位随机值"
    exit 1
fi

if [[ ! -f "$IMAGE_TAR" ]]; then
    echo "ERROR: 未找到 QA 镜像包: $IMAGE_TAR"
    exit 1
fi

echo "[1/6] 加载 QA 热修复镜像..."
docker load -i "$IMAGE_TAR"

echo "[2/6] 校验镜像内置 Skill 目录..."
docker run --rm --entrypoint python assessment-qa:latest \
    -c "from agents.skill_catalog import load_catalog; catalog=load_catalog(); assert len(catalog['skills']) == 30; print('Skill catalog OK:', len(catalog['skills']))"

echo "[3/6] 导出只读 Skill Markdown 目录..."
mkdir -p "$DATA_DIR/qa" "$DATA_DIR/config"
SKILLS_DIR="$DATA_DIR/config/skills"
SKILLS_TMP_DIR="$DATA_DIR/config/skills.tmp.$$"
EXPORT_CONTAINER="assessment-qa-catalog-export-$$"
docker rm -f "$EXPORT_CONTAINER" >/dev/null 2>&1 || true
docker create --name "$EXPORT_CONTAINER" assessment-qa:latest >/dev/null
rm -rf "$SKILLS_TMP_DIR"
mkdir -p "$SKILLS_TMP_DIR"
if ! docker cp "$EXPORT_CONTAINER:/app/config/skills/." "$SKILLS_TMP_DIR"; then
    docker rm -f "$EXPORT_CONTAINER" >/dev/null 2>&1 || true
    rm -rf "$SKILLS_TMP_DIR"
    echo "ERROR: 无法导出 /app/config/skills"
    exit 1
fi
docker rm "$EXPORT_CONTAINER" >/dev/null
rm -rf "$SKILLS_DIR"
mv "$SKILLS_TMP_DIR" "$SKILLS_DIR"
test -s "$SKILLS_DIR/README.md"
test "$(find "$SKILLS_DIR" -mindepth 2 -maxdepth 2 -name SKILL.md -type f | wc -l)" -eq 30

echo "[4/6] 强制替换旧 QA 容器..."
# Compose 通常会给网络名加项目名前缀。优先沿用旧 QA 容器（其次是
# admin 容器）所在的应用网络，避免热修复后跨服务 DNS 失效。
if [[ -z "$NETWORK_NAME" ]]; then
    for peer_container in assessment-qa assessment-admin; do
        if docker ps -a --format '{{.Names}}' | grep -qx "$peer_container"; then
            NETWORK_NAME="$(
                docker inspect "$peer_container" \
                    --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
                    | grep -Ev '^(bridge|host|none)$' \
                    | head -n 1 \
                    || true
            )"
            [[ -n "$NETWORK_NAME" ]] && break
        fi
    done
fi
NETWORK_NAME="${NETWORK_NAME:-assessment-net}"
echo "  使用网络: $NETWORK_NAME"
docker network inspect "$NETWORK_NAME" >/dev/null 2>&1 || docker network create "$NETWORK_NAME"
if docker ps -a --format '{{.Names}}' | grep -qx assessment-qa; then
    docker rm -f assessment-qa >/dev/null
fi
docker run -d --name assessment-qa \
    --network "$NETWORK_NAME" \
    -p "$QA_PORT:10253" \
    -e ADMIN_SERVICE_URL="${ADMIN_SERVICE_URL:-http://assessment-admin:10258}" \
    -e KNOWLEDGE_SERVICE_URL="${KNOWLEDGE_SERVICE_URL:-http://assessment-knowledge:10252}" \
    -e ONTOLOGY_SERVICE_URL="${ONTOLOGY_SERVICE_URL:-http://assessment-ontology:10256}" \
    -e INTERNAL_SERVICE_TOKEN="$INTERNAL_SERVICE_TOKEN" \
    -e EVALUATION_SKILLS_DIR="/app/config/skills" \
    -v "$DATA_DIR/qa:/app/data" \
    -v "$SKILLS_DIR:/app/config/skills:ro" \
    --restart always \
    assessment-qa:latest >/dev/null

echo "[5/6] 核对运行容器与镜像..."
EXPECTED_IMAGE_ID="$(docker image inspect assessment-qa:latest --format '{{.Id}}')"
ACTUAL_IMAGE_ID="$(docker inspect assessment-qa --format '{{.Image}}')"
if [[ "$EXPECTED_IMAGE_ID" != "$ACTUAL_IMAGE_ID" ]]; then
    echo "ERROR: QA 容器仍在使用旧镜像"
    echo "  expected=$EXPECTED_IMAGE_ID"
    echo "  actual=$ACTUAL_IMAGE_ID"
    exit 1
fi
docker exec assessment-qa test -s /app/config/skills/README.md

echo "[6/6] 验证健康检查和 Skill 目录接口..."
QA_READY=0
for i in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$QA_PORT/health" >/dev/null 2>&1; then
        QA_READY=1
        break
    fi
    sleep 1
done
if [[ "$QA_READY" -ne 1 ]]; then
    echo "ERROR: QA 服务未通过健康检查"
    docker logs --tail 100 assessment-qa
    exit 1
fi

SKILL_RESPONSE="$(curl -fsS "http://127.0.0.1:$QA_PORT/evaluation/skills")"
if ! echo "$SKILL_RESPONSE" | grep -Eq '"builtInTotal"[[:space:]]*:[[:space:]]*30'; then
    echo "ERROR: Skill 目录接口未返回 30 个内置 Skill"
    echo "$SKILL_RESPONSE"
    exit 1
fi

echo "QA Skill 热修复完成"
echo "  image=$ACTUAL_IMAGE_ID"
echo "  catalog=/app/config/skills"
echo "  builtInTotal=30"
