#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
BUILD_DIR="$SCRIPT_DIR/build"
INSTALL_DIR="$PROJECT_DIR/dist/Stella.app"
APP_DIR="$BUILD_DIR/Stella.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
ICONSET_DIR="$BUILD_DIR/AppIcon.iconset"
ICON_SOURCE="$SCRIPT_DIR/StellaIcon.png"
ICON_CANVAS="$BUILD_DIR/StellaIconCanvas.png"

if [[ "$INSTALL_DIR" != "$PROJECT_DIR/dist/Stella.app" ]]; then
  print -u2 "应用输出路径异常，已停止。"
  exit 1
fi

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$MACOS_DIR" "$RESOURCES_DIR" "$ICONSET_DIR"
cp "$SCRIPT_DIR/Info.plist" "$CONTENTS_DIR/Info.plist"
/usr/libexec/PlistBuddy -c "Set :LegalKBFrontendPath $PROJECT_DIR/frontend" "$CONTENTS_DIR/Info.plist"
ARCHITECTURE="$(uname -m)"
SPARKLE_SDK="$(python3 "$PROJECT_DIR/scripts/distribution/configure_local_updates.py" "$CONTENTS_DIR/Info.plist" --arch "$ARCHITECTURE")"
SPARKLE_SWIFT_FLAGS=("${(@f)$(python3 "$PROJECT_DIR/scripts/distribution/configure_local_updates.py" --swift-flags)}")

xcrun swiftc \
  -O \
  -whole-module-optimization \
  -target "$ARCHITECTURE-apple-macosx12.0" \
  -framework Cocoa \
  -framework WebKit \
  -framework LocalAuthentication \
  -framework EventKit \
  -framework UserNotifications \
  "${SPARKLE_SWIFT_FLAGS[@]}" \
  -F "$SPARKLE_SDK" -framework Sparkle \
  -Xlinker -rpath -Xlinker '@executable_path/../Frameworks' \
  "$SCRIPT_DIR/Sources/main.swift" \
  "$SCRIPT_DIR/Sources/ApplicationUpdates.swift" \
  "$SCRIPT_DIR/Sources/UpdateInstallationPolicy.swift" \
  -o "$MACOS_DIR/Stella"

# Run the EventKit bridge from inside the Stella bundle.  This gives macOS a
# stable, signed application identity for Calendar privacy consent instead of
# attributing the request to a transient `swift` command-line process.
xcrun swiftc \
  -O \
  -target "$ARCHITECTURE-apple-macosx12.0" \
  -framework EventKit \
  "$PROJECT_DIR/backend/calendar_bridge.swift" \
  -o "$MACOS_DIR/APEXCalendarBridge"

mkdir -p "$CONTENTS_DIR/Frameworks"
ditto "$SPARKLE_SDK/Sparkle.framework" "$CONTENTS_DIR/Frameworks/Sparkle.framework"
cp "$ICON_SOURCE" "$RESOURCES_DIR/StellaBrand.png"

xcrun swiftc "$SCRIPT_DIR/create_stella_icon.swift" -o "$BUILD_DIR/create-stella-icon"
"$BUILD_DIR/create-stella-icon" "$ICON_SOURCE" "$ICON_CANVAS"
sips -z 16 16 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -z 32 32 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -z 64 64 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -z 256 256 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -z 512 512 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$ICON_CANVAS" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
cp "$ICON_CANVAS" "$ICONSET_DIR/icon_512x512@2x.png"
iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/AppIcon.icns"

chmod 755 "$MACOS_DIR/Stella"
codesign --force --deep --sign - "$APP_DIR"

mkdir -p "$PROJECT_DIR/dist" "$PROJECT_DIR/.tmp"
RECOVERY_DIR="$(mktemp -d "$PROJECT_DIR/.tmp/stella-native-before-build.XXXXXX")"
PREVIOUS_APP="$RECOVERY_DIR/Stella.app"
if [[ -d "$INSTALL_DIR" ]]; then
  mv "$INSTALL_DIR" "$PREVIOUS_APP"
fi
if ! mv "$APP_DIR" "$INSTALL_DIR"; then
  if [[ -d "$PREVIOUS_APP" ]]; then mv "$PREVIOUS_APP" "$INSTALL_DIR"; fi
  exit 1
fi
print "$INSTALL_DIR"
