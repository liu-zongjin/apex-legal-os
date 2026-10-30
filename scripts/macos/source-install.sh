#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
ACTION="${1:-check}"
VENV="$ROOT/.venv"
PYTHON="${STELLA_PYTHON:-$(command -v python3.12 || true)}"
APP="${STELLA_SOURCE_APP_DIR:-$HOME/Applications/Stella Source.app}"

fail() { printf '%s\n' "$*" >&2; exit 1; }
case "$ACTION" in
  check|install|diagnose|client) ;;
  *) fail '使用方式：bash scripts/macos/source-install.sh check|install|diagnose|client' ;;
esac
[[ "$(uname -s)" == Darwin ]] || fail '此流程仅适用于 macOS。'
[[ "$(uname -m)" == arm64 || "$(uname -m)" == x86_64 ]] || fail '需要 Apple 芯片或 Intel Mac。'
printf '源码目录：%s\n应用入口：%s\n' "$ROOT" "$APP"
if [[ -n "$PYTHON" ]] && "$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12)' 2>/dev/null; then
  printf 'Python 3.12：%s\n' "$PYTHON"
else
  PYTHON=''
  printf '尚未找到 Python 3.12。\n'
fi
if [[ "$ACTION" == check ]]; then
  xcrun --find swiftc >/dev/null 2>&1 && printf 'Swift 编译工具可用。\n' || printf '尚未找到 Apple 命令行开发工具。\n'
  exit 0
fi
if [[ "$ACTION" == install ]]; then
  [[ -n "$PYTHON" ]] || fail '请先安装适合本机架构的 Python 3.12。'
  if [[ -e "$VENV" || -L "$VENV" ]]; then
    [[ ! -L "$VENV" && -f "$VENV/.stella-source-managed" && -x "$VENV/bin/python" ]] || fail '现有虚拟环境来源不明或不完整，已保留；请先检查。'
  else
    "$PYTHON" -m venv "$VENV"
    : > "$VENV/.stella-source-managed"
  fi
  "$VENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12)' || fail '现有虚拟环境不是 Python 3.12。'
  "$VENV/bin/python" -m pip install --no-cache-dir -r "$ROOT/requirements-private.txt" 'playwright==1.64.0' 'Send2Trash==1.8.3'
  "$VENV/bin/python" -m pip check
  "$VENV/bin/python" -m playwright install chromium
  exit 0
fi
[[ -x "$VENV/bin/python" ]] || fail '请先执行 install。'
if [[ "$ACTION" == diagnose ]]; then
  "$VENV/bin/python" -m pip check
  "$VENV/bin/python" -c 'import fastapi,uvicorn,fitz,docx,openpyxl,playwright'
  exit 0
fi
[[ ! -e "$APP" && ! -L "$APP" ]] || fail '目标应用已存在，未覆盖；请使用更新流程或检查该应用。'
xcrun --find swiftc >/dev/null 2>&1 || fail '请先安装 Apple 命令行开发工具。'
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/stella-source-build.XXXXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
BUNDLE="$STAGE/Stella Source.app"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources" "$STAGE/AppIcon.iconset"
cp "$ROOT/native-shell/Info.plist" "$BUNDLE/Contents/Info.plist"
"$VENV/bin/python" - "$BUNDLE/Contents/Info.plist" "$ROOT" <<'PY'
import plistlib, sys
from pathlib import Path
path = Path(sys.argv[1])
info = plistlib.loads(path.read_bytes())
info.update(CFBundleIdentifier='com.stella.source.native', CFBundleName='Stella Source',
            CFBundleDisplayName='Stella Source', LegalKBFrontendPath=str(Path(sys.argv[2])/'frontend'),
            StellaSourceRoot=sys.argv[2], LSMinimumSystemVersion='12.0')
path.write_bytes(plistlib.dumps(info))
PY
ARCH="$(uname -m)"
xcrun swiftc -O -whole-module-optimization -D STELLA_SOURCE -target "$ARCH-apple-macosx12.0" \
  -framework Cocoa -framework WebKit -framework LocalAuthentication -framework EventKit -framework UserNotifications \
  "$ROOT/native-shell/Sources/main.swift" "$ROOT/native-shell/Sources/SourceDistribution.swift" \
  "$ROOT/native-shell/Sources/SourceApplicationUpdates.swift" -o "$BUNDLE/Contents/MacOS/Stella"
xcrun swiftc -O -target "$ARCH-apple-macosx12.0" -framework EventKit "$ROOT/backend/calendar_bridge.swift" -o "$BUNDLE/Contents/MacOS/APEXCalendarBridge"
xcrun swiftc -O -target "$ARCH-apple-macosx12.0" -framework Contacts "$ROOT/backend/contacts_bridge.swift" -o "$BUNDLE/Contents/MacOS/APEXContactsBridge"
xcrun swiftc -O -target "$ARCH-apple-macosx12.0" -framework Cocoa -framework Vision "$ROOT/backend/court_directory_vision_ocr.swift" -o "$BUNDLE/Contents/MacOS/APEXVisionOCR"
cp "$ROOT/native-shell/StellaIcon.png" "$BUNDLE/Contents/Resources/StellaBrand.png"
xcrun swiftc "$ROOT/native-shell/create_stella_icon.swift" -o "$STAGE/create-stella-icon"
"$STAGE/create-stella-icon" "$ROOT/native-shell/StellaIcon.png" "$STAGE/icon.png"
for spec in '16 16x16' '32 16x16@2x' '32 32x32' '64 32x32@2x' '128 128x128' '256 128x128@2x' '256 256x256' '512 256x256@2x' '512 512x512'; do
  set -- $spec
  sips -z "$1" "$1" "$STAGE/icon.png" --out "$STAGE/AppIcon.iconset/icon_$2.png" >/dev/null
done
cp "$STAGE/icon.png" "$STAGE/AppIcon.iconset/icon_512x512@2x.png"
iconutil -c icns "$STAGE/AppIcon.iconset" -o "$BUNDLE/Contents/Resources/AppIcon.icns"
codesign --force --deep --sign - "$BUNDLE"
mkdir -p "$(dirname "$APP")"
[[ ! -e "$APP" && ! -L "$APP" ]] || fail '目标应用在构建期间出现，未覆盖。'
mv "$BUNDLE" "$APP"
printf '源码客户端已创建：%s\n' "$APP"
