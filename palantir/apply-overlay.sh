#!/usr/bin/env sh
set -eu
TARGET="${1:-.}"
OVERLAY="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ ! -f "$TARGET/docker-compose.yml" ] || [ ! -d "$TARGET/src/frontend" ]; then
  echo "Target does not look like palantir-ghotam-like: $TARGET" >&2
  exit 1
fi

if [ ! -f "$TARGET/docker-compose.pre-v7.yml" ]; then
  cp "$TARGET/docker-compose.yml" "$TARGET/docker-compose.pre-v7.yml"
fi

cp -R "$OVERLAY/src/." "$TARGET/src/"
cp -R "$OVERLAY/data/." "$TARGET/data/"
mkdir -p "$TARGET/docs"
cp -R "$OVERLAY/docs/." "$TARGET/docs/"
cp "$OVERLAY/docker-compose.yml" "$TARGET/docker-compose.yml"
rm -f "$TARGET/docker-compose.dynamic.yml"
rm -f "$TARGET/src/frontend/package-lock.json"
rm -f "$TARGET/src/backend/Aegis.Infrastructure/AI/OllamaService.cs"

echo "AEGIS Dynamic Ontology v7 applied."
echo "Add a NEW DEEPSEEK_API_KEY to .env, then run: docker compose up -d --build"
