#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f "$PROJECT_DIR/.env.private" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_DIR/.env.private"
  set +a
fi

export LEGAL_KB_PRIVATE_MODE="${LEGAL_KB_PRIVATE_MODE:-1}"
export LEGAL_KB_ALLOW_REMOTE_MANAGEMENT="${LEGAL_KB_ALLOW_REMOTE_MANAGEMENT:-0}"
export PORT="${PORT:-8000}"
# Remote devices reach this app through Tailscale Serve, which terminates TLS
# on the tailnet URL and proxies to this loopback-only backend.
export LEGAL_KB_HOST="${LEGAL_KB_HOST:-127.0.0.1}"

PYTHON_BIN="${LEGAL_KB_PYTHON:-$(command -v python3)}"
exec "$PYTHON_BIN" -m uvicorn backend.main:app --host "$LEGAL_KB_HOST" --port "$PORT"
