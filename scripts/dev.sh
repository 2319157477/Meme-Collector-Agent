#!/usr/bin/env bash
set -euo pipefail
python -m uvicorn meme_collector_app.main:create_app --factory --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"
