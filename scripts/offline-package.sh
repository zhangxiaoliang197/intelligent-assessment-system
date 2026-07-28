#!/bin/bash
set -euo pipefail

# Build the canonical assessment-* images, run the QA Skill catalog gate, and
# package exactly the directories consumed by deploy/deploy-centos7.sh.
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE_NAME="assessment-offline-$(date +%Y%m%d-%H%M%S).tar.gz"

echo "========================================"
echo "智能评估系统 - 离线部署包"
echo "========================================"

bash "$PROJECT_DIR/deploy/build-images.sh"

echo "[打包] $PACKAGE_NAME"
tar -czf "$PROJECT_DIR/$PACKAGE_NAME" \
    -C "$PROJECT_DIR" \
    docker-images \
    deploy

echo "离线部署包已生成: $PROJECT_DIR/$PACKAGE_NAME"
echo "目标机部署命令:"
echo "  tar -xzf $PACKAGE_NAME"
echo "  bash deploy/deploy-centos7.sh"
