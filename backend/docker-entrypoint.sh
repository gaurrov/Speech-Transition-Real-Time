#!/bin/sh
# Backend container entrypoint: run FastAPI behind the production ASGI server.
# All knobs are environment-driven; nothing is baked into the image.
set -eu

: "${HOST:=0.0.0.0}"
: "${PORT:=8000}"
: "${WORKERS:=1}"
: "${LOG_LEVEL:=INFO}"

# uvicorn wants lowercase log levels.
log_level=$(printf '%s' "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')

exec uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --log-level "$log_level" \
    --ws-ping-interval 20 \
    --ws-ping-timeout 20
