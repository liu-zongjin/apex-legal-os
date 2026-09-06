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

find_tailscale() {
  for candidate in \
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale" \
    "/opt/homebrew/bin/tailscale" \
    "/usr/local/bin/tailscale" \
    "$(command -v tailscale 2>/dev/null || true)"
  do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

ip_is_local() {
  local candidate="$1"
  ifconfig 2>/dev/null | awk -v wanted="$candidate" '
    $1 == "inet" && $2 == wanted { found = 1 }
    END { exit(found ? 0 : 1) }
  '
}

if [ -z "${LEGAL_KB_HOST:-}" ]; then
  if TAILSCALE_BIN="$(find_tailscale)"; then
    # The CLI may retain and print the previous Tailscale IP while the
    # interface is stopped. Only bind an address that currently belongs to
    # this Mac, otherwise uvicorn enters a launchd crash loop with Errno 49.
    candidate_ip="$("$TAILSCALE_BIN" ip -4 2>/dev/null | head -n 1 || true)"
    if [ -n "$candidate_ip" ] && ip_is_local "$candidate_ip"; then
      LEGAL_KB_HOST="$candidate_ip"
    fi
  fi
  # If Tailscale is slow to expose its CLI IP, bind all local interfaces.
  # The app is still password-protected, and this avoids a silent localhost-only start.
  export LEGAL_KB_HOST="${LEGAL_KB_HOST:-0.0.0.0}"
fi

PYTHON_BIN="${LEGAL_KB_PYTHON:-$(command -v python3)}"
exec "$PYTHON_BIN" -m uvicorn backend.main:app --host "$LEGAL_KB_HOST" --port "$PORT"
