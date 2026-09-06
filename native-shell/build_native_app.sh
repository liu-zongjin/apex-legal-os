#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
BUILD_DIR="$SCRIPT_DIR/build"
APP_DIR="$PROJECT_DIR/dist/APEX.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
ICONSET_DIR="$BUILD_DIR/AppIcon.iconset"
ICON_SOURCE="$PROJECT_DIR/frontend/static/app-icon-1024.png"

if [[ "$APP_DIR" != "$PROJECT_DIR/dist/APEX.app" ]]; then
  print -u2 "应用输出路径异常，已停止。"
  exit 1
fi

rm -rf "$BUILD_DIR" "$APP_DIR"
mkdir -p "$BUILD_DIR" "$MACOS_DIR" "$RESOURCES_DIR" "$ICONSET_DIR"

xcrun swiftc \
  -O \
  -whole-module-optimization \
  -target arm64-apple-macosx11.3 \
  -framework Cocoa \
  -framework WebKit \
  -framework LocalAuthentication \
  -framework EventKit \
  -framework UserNotifications \
  "$SCRIPT_DIR/Sources/main.swift" \
  -o "$MACOS_DIR/APEX"

# Run the EventKit bridge from inside the APEX bundle.  This gives macOS a
# stable, signed application identity for Calendar privacy consent instead of
# attributing the request to a transient `swift` command-line process.
xcrun swiftc \
  -O \
  -target arm64-apple-macosx11.3 \
  -framework EventKit \
  "$PROJECT_DIR/backend/calendar_bridge.swift" \
  -o "$MACOS_DIR/APEXCalendarBridge"

cp "$SCRIPT_DIR/Info.plist" "$CONTENTS_DIR/Info.plist"
/usr/libexec/PlistBuddy \
  -c "Set :LegalKBFrontendPath $PROJECT_DIR/frontend" \
  "$CONTENTS_DIR/Info.plist"

sips -z 16 16 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -z 64 64 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
cp "$ICON_SOURCE" "$ICONSET_DIR/icon_512x512@2x.png"
iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/AppIcon.icns"

chmod 755 "$MACOS_DIR/APEX"
codesign --force --deep --sign - "$APP_DIR"

print "$APP_DIR"
