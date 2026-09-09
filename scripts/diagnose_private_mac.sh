#!/bin/bash
set -u

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

LABEL="com.liuzongjin.legalkb.private"
PORT="${PORT:-8000}"

if [ -f "$PROJECT_DIR/.env.private" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_DIR/.env.private"
  set +a
fi

CURL_AUTH=()
if [ -n "${LEGAL_KB_ACCESS_USER:-}" ] && [ -n "${LEGAL_KB_ACCESS_PASSWORD:-}" ]; then
  CURL_AUTH=(-u "$LEGAL_KB_ACCESS_USER:$LEGAL_KB_ACCESS_PASSWORD")
fi

find_tailscale() {
  for candidate in \
    "${LEGAL_KB_TAILSCALE_BIN:-}" \
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

section() {
  printf '\n==== %s ====\n' "$1"
}

section "Project"
printf 'project: %s\n' "$PROJECT_DIR"
printf 'env file: %s\n' "$([ -f "$PROJECT_DIR/.env.private" ] && echo present || echo missing)"
printf 'port: %s\n' "$PORT"
printf 'configured host: %s\n' "${LEGAL_KB_HOST:-auto}"

section "Launchd"
launchctl print "gui/$(id -u)/$LABEL" 2>&1 | sed -n '1,80p'
if launchctl print "gui/$(id -u)/com.liuzongjin.legalkb" >/dev/null 2>&1; then
  printf '\nwarning: legacy com.liuzongjin.legalkb is also loaded; it must be disabled to avoid duplicate schedulers\n'
fi

section "Listening Ports"
if command -v lsof >/dev/null 2>&1; then
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>&1 || true
else
  netstat -an | grep "[.:]$PORT " || true
fi

section "Local HTTP"
for _ in $(seq 1 10); do
  if curl --max-time 1 -sS "${CURL_AUTH[@]}" -o /dev/null "http://127.0.0.1:$PORT/api/server-status" 2>/dev/null; then
    break
  fi
  sleep 1
done
curl --max-time 5 -sS "${CURL_AUTH[@]}" -o /dev/null -w 'GET /api/server-status -> HTTP %{http_code}\n' "http://127.0.0.1:$PORT/api/server-status" 2>&1 || true

section "Judicial Messages"
PYTHON_COMMAND="${LEGAL_KB_PYTHON:-$(command -v python3)}"
PYTHON_BIN="$($PYTHON_COMMAND -c 'import os,sys; print(os.path.realpath(sys.executable))' 2>/dev/null || printf '%s' "$PYTHON_COMMAND")"
PYTHON_REAL="$($PYTHON_BIN -c 'import sys; print(sys.executable)' 2>/dev/null || printf '%s' "$PYTHON_BIN")"
PYTHON_FDA_TARGET="$($PYTHON_BIN -c 'import os,sys; print(os.path.realpath(sys.executable))' 2>/dev/null || printf '%s' "$PYTHON_REAL")"
MESSAGES_DB="$HOME/Library/Messages/chat.db"
printf 'service python: %s\n' "$PYTHON_REAL"
printf 'full disk access target: %s\n' "$PYTHON_FDA_TARGET"
printf 'messages database: %s\n' "$MESSAGES_DB"
if [ ! -e "$MESSAGES_DB" ]; then
  printf 'status: database missing; sign in to Messages on this Mac first\n'
else
  JUDICIAL_STATUS="$(curl --max-time 5 -sS "${CURL_AUTH[@]}" "http://127.0.0.1:$PORT/api/case-manager/judicial-messages/status" 2>/dev/null || true)"
  SERVICE_PERMISSION="$(printf '%s' "$JUDICIAL_STATUS" | "$PYTHON_BIN" -c 'import json,sys; data=json.load(sys.stdin); print("yes" if data.get("permission_granted") else "no")' 2>/dev/null || true)"
  if [ "$SERVICE_PERMISSION" = "yes" ]; then
    printf 'status: readable (verified in LaunchAgent identity)\n'
  elif [ "$SERVICE_PERMISSION" = "no" ]; then
    printf 'status: authorization denied in LaunchAgent identity\n'
    printf 'action: System Settings -> Privacy & Security -> Full Disk Access -> add the full disk access target above\n'
  else
    printf 'status: service unavailable; could not verify LaunchAgent permission\n'
  fi
  printf '%s\n' "$JUDICIAL_STATUS" | sed -n '1,12p'
fi

section "Tailscale"
if TAILSCALE_BIN="$(find_tailscale)"; then
  printf 'tailscale bin: %s\n' "$TAILSCALE_BIN"
  "$TAILSCALE_BIN" ip -4 2>&1 || true
  "$TAILSCALE_BIN" status 2>&1 | sed -n '1,80p' || true
  printf '\nTailscale Serve:\n'
  "$TAILSCALE_BIN" serve status 2>&1 || true
else
  printf 'tailscale cli not found\n'
fi

section "Tailscale HTTPS"
HTTPS_URL="$(bash "$PROJECT_DIR/scripts/private_https_url.sh" 2>/dev/null || true)"
if [ -n "$HTTPS_URL" ]; then
  printf 'private URL: %s\n' "$HTTPS_URL"
  curl --max-time 8 -sS "${CURL_AUTH[@]}" -o /dev/null -w 'GET /api/server-status -> HTTP %{http_code}\n' "$HTTPS_URL/api/server-status" 2>&1 || true
else
  printf 'HTTPS URL unavailable. Enable MagicDNS and HTTPS Certificates in the Tailscale admin console, then rerun the installer.\n'
fi

section "Recent Server Log"
tail -n 80 "$PROJECT_DIR/logs/private-server.log" 2>&1 || true

section "Next URL"
if [ -n "$HTTPS_URL" ]; then
  printf 'Use from another Tailscale device: %s\n' "$HTTPS_URL"
else
  printf 'No HTTPS address is configured yet; do not use http://IP:%s for mobile offline access.\n' "$PORT"
fi
