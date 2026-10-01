#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

case "$PROJECT_DIR" in
  "$HOME/Documents"/*|"$HOME/Desktop"/*|"$HOME/Downloads"/*|"$HOME/Library/Mobile Documents"/*)
    cat <<EOF
当前目录位于 macOS 隐私保护目录：
$PROJECT_DIR

后台自启动服务可能无法访问 Documents/Desktop/Downloads/iCloud Drive。
请把 legal-kb 移到用户主目录后再运行，例如：

  mv "$PROJECT_DIR" "$HOME/legal-kb"
  cd "$HOME/legal-kb"
  bash scripts/install_private_mac.sh

EOF
    exit 1
    ;;
esac

LABEL="com.liuzongjin.legalkb.private"
BACKUP_LABEL="com.liuzongjin.legalkb.private.backup"
LEGACY_LABEL="com.liuzongjin.legalkb"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_DIR/$LABEL.plist"
BACKUP_PLIST_PATH="$LAUNCH_DIR/$BACKUP_LABEL.plist"
LOG_DIR="$PROJECT_DIR/logs"
ENV_PATH="$PROJECT_DIR/.env.private"
PYTHON_COMMAND="${LEGAL_KB_PYTHON:-$(command -v python3)}"
PYTHON_BIN="$("$PYTHON_COMMAND" -c 'import os,sys; print(os.path.realpath(sys.executable))')"

mkdir -p "$LAUNCH_DIR" "$LOG_DIR" "$HOME/LegalKBBackups"

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

ensure_env_default() {
  local key="$1"
  local value="$2"
  if ! grep -q "^${key}=" "$ENV_PATH"; then
    printf '%s=%q\n' "$key" "$value" >> "$ENV_PATH"
  fi
}

if [ ! -f "$ENV_PATH" ]; then
  printf "首次配置私有访问登录信息。\n"
  read -r -p "登录用户名 [lawyer]: " ACCESS_USER
  ACCESS_USER="${ACCESS_USER:-lawyer}"
  while true; do
    read -r -s -p "登录密码: " ACCESS_PASSWORD
    printf "\n"
    read -r -s -p "再次输入登录密码: " ACCESS_PASSWORD_CONFIRM
    printf "\n"
    if [ -n "$ACCESS_PASSWORD" ] && [ "$ACCESS_PASSWORD" = "$ACCESS_PASSWORD_CONFIRM" ]; then
      break
    fi
    printf "两次密码不一致，或密码为空，请重试。\n"
  done
  {
    printf 'LEGAL_KB_PRIVATE_MODE=1\n'
    printf 'LEGAL_KB_ALLOW_REMOTE_MANAGEMENT=0\n'
    printf 'LEGAL_KB_ACCESS_USER=%q\n' "$ACCESS_USER"
    printf 'LEGAL_KB_ACCESS_PASSWORD=%q\n' "$ACCESS_PASSWORD"
    # Tailscale Serve is the only remote entry point. Keeping Uvicorn on the
    # loopback interface prevents an insecure HTTP LAN endpoint from bypassing
    # the HTTPS requirement needed by mobile Service Workers.
    printf 'LEGAL_KB_HOST=127.0.0.1\n'
    printf 'PORT=8000\n'
    printf 'LEGAL_KB_BACKUP_DIR=%q\n' "$HOME/LegalKBBackups"
    printf 'LEGAL_KB_BACKUP_RETENTION_DAYS=14\n'
  } > "$ENV_PATH"
  chmod 600 "$ENV_PATH"
fi

# Upgrade existing private installs without overwriting an intentional custom
# bind address. The default becomes loopback-only, with Tailscale Serve as the
# private HTTPS gateway.
ensure_env_default 'LEGAL_KB_HOST' '127.0.0.1'
chmod 600 "$ENV_PATH"

set -a
# shellcheck disable=SC1090
. "$ENV_PATH"
set +a

if ! TAILSCALE_BIN="$(find_tailscale)"; then
  printf 'Tailscale CLI not found. Install Tailscale, sign in, then rerun this installer.\n' >&2
  exit 1
fi
if ! "$TAILSCALE_BIN" status --json >/dev/null 2>&1; then
  printf 'Tailscale is not ready. Sign in to Tailscale, then rerun this installer.\n' >&2
  exit 1
fi

"$PYTHON_BIN" -m pip install -r "$PROJECT_DIR/requirements-private.txt"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$PROJECT_DIR/scripts/private_server.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/private-server.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/private-server.log</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
</dict>
</plist>
EOF

cat > "$BACKUP_PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$BACKUP_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_DIR/scripts/backup_private.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/private-backup.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/private-backup.log</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>3</integer>
    <key>Minute</key>
    <integer>20</integer>
  </dict>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF

"$PYTHON_BIN" - "$BACKUP_PLIST_PATH" "${LEGAL_KB_BACKUP_DIR:-$HOME/LegalKBBackups}/backup-settings.json" <<'PY'
import json, plistlib, sys
from pathlib import Path

plist_path, settings_path = map(Path, sys.argv[1:])
if settings_path.is_file():
    settings = json.loads(settings_path.read_text(encoding='utf-8'))
    timing = {'Hour': settings['hour'], 'Minute': settings['minute']}
    frequency = settings['frequency']
    if frequency == 'weekly':
        interval = {**timing, 'Weekday': settings['weekday']}
    elif frequency == 'weekdays':
        interval = [{**timing, 'Weekday': day} for day in range(1, 6)]
    elif frequency == 'daily':
        interval = timing
    else:
        raise SystemExit('Invalid backup frequency')
    plist = plistlib.loads(plist_path.read_bytes())
    plist['StartCalendarInterval'] = interval
    plist_path.write_bytes(plistlib.dumps(plist))
PY

chmod 644 "$PLIST_PATH" "$BACKUP_PLIST_PATH"
chmod +x "$PROJECT_DIR/scripts/start_private_server.sh" "$PROJECT_DIR/scripts/private_server.py" "$PROJECT_DIR/scripts/backup_private.sh" "$PROJECT_DIR/scripts/diagnose_private_mac.sh" "$PROJECT_DIR/scripts/private_https_url.sh"

# Older installations used a second always-on service on 127.0.0.1:8000.
# Leaving it enabled creates two independent schedulers and makes localhost
# health checks report the wrong process. Persistently disable that legacy
# label while keeping its plist on disk for a reversible migration.
launchctl disable "gui/$(id -u)/$LEGACY_LABEL" >/dev/null 2>&1 || true
launchctl bootout "gui/$(id -u)/$LEGACY_LABEL" >/dev/null 2>&1 || true
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootout "gui/$(id -u)" "$BACKUP_PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl bootstrap "gui/$(id -u)" "$BACKUP_PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

# Tailscale terminates TLS and keeps this reverse-proxy configuration in its
# daemon, independently of the app LaunchAgent. The command may ask to enable
# HTTPS for the tailnet on first use.
if ! "$TAILSCALE_BIN" serve --bg --https=443 "http://127.0.0.1:$PORT"; then
  cat >&2 <<EOF
无法配置 Tailscale HTTPS 入口。
请在 Tailscale 管理后台的 DNS 页面启用 MagicDNS 和 HTTPS Certificates，
然后重新运行本安装脚本。
EOF
  exit 1
fi

HTTPS_URL="$(bash "$PROJECT_DIR/scripts/private_https_url.sh")"

printf "\n安装完成。\n"
printf "请在同一 Tailscale 网络的设备上访问：%s\n" "$HTTPS_URL"
printf "请勿再使用 http://IP:8000；该地址不能启用移动端离线缓存。\n"
printf "服务日志：%s/private-server.log\n" "$LOG_DIR"
printf "备份目录：%s\n" "$HOME/LegalKBBackups"
SERVICE_PYTHON="$PYTHON_BIN"
SERVICE_PYTHON_REAL="$($SERVICE_PYTHON -c 'import sys; print(sys.executable)' 2>/dev/null || printf '%s' "$SERVICE_PYTHON")"
SERVICE_FDA_TARGET="$($SERVICE_PYTHON -c 'import os,sys; print(os.path.realpath(sys.executable))' 2>/dev/null || printf '%s' "$SERVICE_PYTHON_REAL")"
printf "\n司法短信读取还需要一次 macOS 授权：\n"
printf "1. 打开 系统设置 -> 隐私与安全性 -> 完全磁盘访问权限。\n"
printf "2. 添加并启用：%s\n" "$SERVICE_FDA_TARGET"
printf "3. 重启服务：launchctl kickstart -k gui/%s/%s\n" "$(id -u)" "$LABEL"
printf "4. 运行诊断：bash %s/scripts/diagnose_private_mac.sh\n" "$PROJECT_DIR"
