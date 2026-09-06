#!/bin/bash
# ============================================================
#  法律操作系统 - Mac 打包脚本
#  运行方式：cd legal-kb && bash build_mac.sh
#  产出：dist/法律操作系统.app  和  dist/法律操作系统_Mac.zip
# ============================================================

set -e  # 遇到错误立即退出

APP_NAME="法律操作系统"
ENTRY="app_entry.py"
DIST_DIR="dist"
BUILD_DIR="build"

echo ""
echo "======================================================"
echo "  法律操作系统 Mac 打包脚本"
echo "======================================================"
echo ""

# ── 1. 检查 Python ──────────────────────────────────────────
echo "[1/6] 检查 Python 环境..."
if ! command -v python3 &>/dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.8+"
    exit 1
fi
PYTHON=$(command -v python3)
echo "    Python: $($PYTHON --version)"

# ── 2. 安装/更新依赖 ─────────────────────────────────────────
echo ""
echo "[2/6] 安装打包依赖..."
$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet \
    pyinstaller \
    fastapi \
    uvicorn[standard] \
    requests \
    httpx \
    beautifulsoup4 \
    lxml \
    jieba \
    watchfiles \
    xlrd \
    Pillow \
    aiofiles \
    python-multipart
echo "    ✅ 依赖安装完成"

# ── 3. 清理旧产物 ────────────────────────────────────────────
echo ""
echo "[3/6] 清理旧打包产物..."
rm -rf "$BUILD_DIR" "$DIST_DIR" __pycache__ *.spec
echo "    ✅ 清理完成"

# ── 4. 执行打包 ──────────────────────────────────────────────
echo ""
echo "[4/6] 开始打包（可能需要几分钟）..."

$PYTHON -m PyInstaller \
    --name "$APP_NAME" \
    --onedir \
    --windowed \
    --noconfirm \
    --clean \
    --add-data "frontend:frontend" \
    --add-data "backend:backend" \
    --hidden-import "uvicorn.logging" \
    --hidden-import "uvicorn.loops" \
    --hidden-import "uvicorn.loops.auto" \
    --hidden-import "uvicorn.protocols" \
    --hidden-import "uvicorn.protocols.http" \
    --hidden-import "uvicorn.protocols.http.auto" \
    --hidden-import "uvicorn.protocols.websockets" \
    --hidden-import "uvicorn.protocols.websockets.auto" \
    --hidden-import "uvicorn.lifespan" \
    --hidden-import "uvicorn.lifespan.on" \
    --hidden-import "anyio" \
    --hidden-import "anyio._backends._asyncio" \
    --hidden-import "starlette" \
    --hidden-import "fastapi" \
    --hidden-import "jieba" \
    --hidden-import "bs4" \
    --hidden-import "lxml" \
    --hidden-import "aiofiles" \
    --hidden-import "httpx" \
    --hidden-import "multipart" \
    --collect-all jieba \
    --collect-all bs4 \
    "$ENTRY"

echo "    ✅ 打包完成"

# ── 5. 复制数据库到产出目录 ──────────────────────────────────
echo ""
echo "[5/6] 复制数据库..."
if [ -f "legal_kb.db" ]; then
    cp "legal_kb.db" "$DIST_DIR/$APP_NAME/"
    echo "    ✅ 数据库已复制"
else
    echo "    ⚠️  未找到 legal_kb.db，跳过"
fi

# 创建 uploads 目录
mkdir -p "$DIST_DIR/$APP_NAME/uploads"

# ── 6. 打包成 ZIP ────────────────────────────────────────────
echo ""
echo "[6/6] 压缩为 ZIP..."
cd "$DIST_DIR"
zip -r "${APP_NAME}_Mac.zip" "$APP_NAME"
cd ..
echo "    ✅ 已生成: $DIST_DIR/${APP_NAME}_Mac.zip"

echo ""
echo "======================================================"
echo "  ✅ 打包成功！"
echo ""
echo "  产出文件:"
echo "    $DIST_DIR/${APP_NAME}_Mac.zip"
echo ""
echo "  使用方法:"
echo "    1. 将 ZIP 发给朋友"
echo "    2. 解压后进入 $APP_NAME 文件夹"
echo "    3. 双击「$APP_NAME」运行"
echo "    4. 浏览器会自动打开 http://localhost:8765"
echo "======================================================"
echo ""
