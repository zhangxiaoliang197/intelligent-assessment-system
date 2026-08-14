#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "ERROR: 未找到 docker compose 或 docker-compose"
    exit 1
fi

echo "========================================"
echo "智能评估系统 - 以当前镜像重建服务"
echo "========================================"

"${COMPOSE[@]}" up -d --force-recreate

QA_READY=0
for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:10253/health >/dev/null 2>&1; then
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

SKILL_RESPONSE="$(curl -fsS http://127.0.0.1:10253/evaluation/skills)"
if ! echo "$SKILL_RESPONSE" | grep -Eq '"builtInTotal"[[:space:]]*:[[:space:]]*30'; then
    echo "ERROR: Skill 目录接口未返回 30 个内置 Skill"
    echo "$SKILL_RESPONSE"
    exit 1
fi

echo "Skill 目录校验通过: 30 个内置 Skill"

SITUATION_READY=0
for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:10257/situation/health >/dev/null 2>&1; then
        SITUATION_READY=1
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
"${COMPOSE[@]}" ps
echo "访问地址: http://localhost:10086"
