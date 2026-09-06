#!/bin/bash
# 一键启动所有服务

echo "🚀 启动法律操作系统完整服务..."

# 进入项目目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检查并安装依赖
echo "📦 检查依赖..."

# 检查 Python 依赖
if ! python3 -c "import flask, requests, beautifulsoup4, uvicorn" 2>/dev/null; then
    echo "⚠️  缺少 Python 依赖，正在安装..."
    pip3 install flask requests beautifulsoup4 lxml uvicorn
fi

# 检查 ngrok
if ! command -v ngrok &> /dev/null; then
    echo "⚠️  ngrok 未安装"
    echo "   请运行: brew install ngrok"
    echo "   或访问: https://ngrok.com/download"
fi

# 启动知识库服务
export PORT="${PORT:-8000}"
echo "🏛️  启动知识库服务 (端口 ${PORT})..."
python3 start.py &
KB_PID=$!

# 等待服务启动
sleep 3

# 检查 ngrok 是否在运行
if pgrep -x "ngrok" > /dev/null; then
    echo "✅ ngrock 已在运行"
else
    echo "📡 启动内网穿透 (ngrok)..."
    ngrok http "${PORT}" &
    NGROK_PID=$!
    sleep 2

    echo ""
    echo "📋 ngrok 公网地址："
    echo "   请查看 ngrok 窗口或访问 http://localhost:4040 获取"
    echo ""
fi

echo "✅ 所有服务已启动！"
echo ""
echo "📍 知识库地址: http://localhost:${PORT}"
echo "📍 ngrok 控制台: http://localhost:4040"
echo ""
echo "💡 提示："
echo "   1. 复制 ngrok 公网地址用于飞书配置"
echo "   2. 飞书监听器已自动启动"
echo "   3. 按 Ctrl+C 可停止所有服务"
echo ""

# 等待用户中断
wait
