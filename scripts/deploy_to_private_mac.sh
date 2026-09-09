#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

REMOTE_HOST="${LEGAL_KB_DEPLOY_HOST:-legal-kb-mac}"
REMOTE_USER="${LEGAL_KB_DEPLOY_USER:-anmeilin}"
REMOTE_DIR="${LEGAL_KB_DEPLOY_DIR:-/Users/anmeilin/legal-kb}"
REMOTE="$REMOTE_USER@$REMOTE_HOST"

RSYNC_EXCLUDES=(
  "--exclude=.git/"
  "--exclude=.DS_Store"
  "--exclude=__pycache__/"
  "--exclude=.pycache_tmp/"
  "--exclude=.pytest_cache/"
  "--exclude=node_modules/"
  "--exclude=dist/"
  "--exclude=build/"
  "--exclude=logs/"
  "--exclude=server.log"
  "--exclude=server.pid"
  "--exclude=bridge.log"
  "--exclude=pending_tasks.db"
  "--exclude=legal_kb.db"
  "--exclude=backend/legal_kb.db"
  "--exclude=legal_knowledge.db"
  "--exclude=uploads/"
  "--exclude=.env.private"
  "--exclude=local_ai_secrets.py"
  "--exclude=feishu_config.py"
)

echo "Deploying legal-kb to $REMOTE:$REMOTE_DIR"
echo

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required but was not found."
  exit 1
fi

echo "[1/5] Checking SSH connection..."
ssh -o ConnectTimeout=8 "$REMOTE" "echo connected"

echo "[2/5] Backing up remote database..."
ssh "$REMOTE" "cd '$REMOTE_DIR' && bash scripts/backup_private.sh || true"

echo "[3/5] Syncing code, excluding database/uploads/private config..."
rsync -az --delete \
  "${RSYNC_EXCLUDES[@]}" \
  "$PROJECT_DIR/" \
  "$REMOTE:$REMOTE_DIR/"

echo "[4/5] Updating permissions, dependencies, and restarting service..."
ssh "$REMOTE" "cd '$REMOTE_DIR' && chmod +x scripts/*.sh && python3 -m pip install -r requirements-private.txt && launchctl kickstart -k gui/\$(id -u)/com.liuzongjin.legalkb.private"

echo "[5/5] Verifying private HTTPS service..."
sleep 3
HTTPS_URL="${LEGAL_KB_DEPLOY_URL:-}"
if [ -z "$HTTPS_URL" ]; then
  HTTPS_URL="$(ssh "$REMOTE" "cd '$REMOTE_DIR' && bash scripts/private_https_url.sh" 2>/dev/null || true)"
fi
if [ -z "$HTTPS_URL" ]; then
  echo "Deploy finished, but the Tailscale HTTPS URL could not be determined."
  echo "On the idle Mac, enable MagicDNS and HTTPS Certificates, then rerun: bash scripts/install_private_mac.sh"
  exit 2
fi
HTTP_CODE="$(curl -sS --max-time 8 -o /dev/null -w "%{http_code}" "$HTTPS_URL/api/server-status" || true)"
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "401" ]; then
  echo "Deploy complete: $HTTPS_URL"
else
  echo "Deploy finished, but the health check returned HTTP $HTTP_CODE."
  echo "Try opening $HTTPS_URL in a browser."
  echo "If it fails, run on the idle Mac: cd '$REMOTE_DIR' && bash scripts/diagnose_private_mac.sh"
  exit 2
fi
