#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-meme-collector-smoke}"
SERVICE_URL="${SERVICE_URL:-http://127.0.0.1:8000/health}"
VOLUME_NAME="${PROJECT_NAME}_meme_collector_data"

cleanup() {
  docker compose -p "$PROJECT_NAME" down >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose -p "$PROJECT_NAME" build
docker compose -p "$PROJECT_NAME" up -d

for _ in $(seq 1 30); do
  if curl -fsS "$SERVICE_URL" >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS "$SERVICE_URL"
docker run --rm -v "${VOLUME_NAME}:/data" busybox test -f /data/meme_collector.sqlite3

docker compose -p "$PROJECT_NAME" restart meme-collector
for _ in $(seq 1 30); do
  if curl -fsS "$SERVICE_URL" >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS "$SERVICE_URL"

echo "Docker smoke verification passed for ${PROJECT_NAME}."
