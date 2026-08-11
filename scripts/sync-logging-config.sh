#!/bin/bash
# ========================================
# 同步 python/common/logging_config.py 到 6 个 Python 服务目录
# ========================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$PROJECT_DIR/python/common/logging_config.py"

if [ ! -f "$SRC" ]; then
    echo "ERROR: 源文件不存在: $SRC"
    exit 1
fi

SERVICES=(knowledge-service qa-service indicator-service evaluation-service ontology-service situation-service)

echo "同步 logging_config.py 到 6 个 Python 服务..."
for svc in "${SERVICES[@]}"; do
    DST="$PROJECT_DIR/python/$svc/logging_config.py"
    cp -f "$SRC" "$DST"
    echo "  已同步: python/$svc/logging_config.py"
done

echo "同步完成。"
