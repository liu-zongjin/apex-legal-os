#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

. "$PROJECT_DIR/scripts/private_env.sh" || exit 1

if [ -n "${LEGAL_KB_RUNTIME_DIR:-}" ] && [ ! -s "${LEGAL_KB_DB_PATH:-$LEGAL_KB_RUNTIME_DIR/legal_kb.db}" ]; then
  printf 'Configured private runtime database is missing or empty\n' >&2
  exit 1
fi

export LEGAL_KB_PRIVATE_MODE="${LEGAL_KB_PRIVATE_MODE:-1}"
export LEGAL_KB_ALLOW_REMOTE_MANAGEMENT="${LEGAL_KB_ALLOW_REMOTE_MANAGEMENT:-0}"
export PORT="${PORT:-8000}"
# Remote devices reach this app through Tailscale Serve, which terminates TLS
# on the tailnet URL and proxies to this loopback-only backend.
export LEGAL_KB_HOST="${LEGAL_KB_HOST:-127.0.0.1}"

PYTHON_BIN="${LEGAL_KB_PYTHON:-$(command -v python3)}"
exec "$PYTHON_BIN" -m uvicorn backend.main:app --host "$LEGAL_KB_HOST" --port "$PORT"
