#!/bin/sh
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUTPUT_DIR="$ROOT_DIR/tests/visual/baselines"
FIXTURE="file://$ROOT_DIR/tests/visual/component-gallery.html"
mkdir -p "$OUTPUT_DIR"
"$CHROME_BIN" --headless=new --disable-gpu --hide-scrollbars --window-size=1440,900 --screenshot="$OUTPUT_DIR/components-light-1440x900.png" "$FIXTURE"
"$CHROME_BIN" --headless=new --disable-gpu --hide-scrollbars --window-size=1440,900 --screenshot="$OUTPUT_DIR/components-dark-1440x900.png" "$FIXTURE?theme=dark"
echo "Visual baselines updated in tests/visual/baselines"
