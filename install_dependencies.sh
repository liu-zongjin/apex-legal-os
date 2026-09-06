#!/bin/bash
# 安装所有必需的依赖

echo "📦 安装 Python 依赖..."

pip3 install flask requests beautifulsoup4 lxml uvicorn

if [ $? -eq 0 ]; then
    echo "✅ Python 依赖安装成功"
else
    echo "❌ Python 依赖安装失败"
    exit 1
fi

echo ""
echo "📦 安装 ngrok..."

if ! command -v ngrok &> /dev/null; then
    brew install ngrok
    if [ $? -eq 0 ]; then
        echo "✅ ngrok 安装成功"
    else
        echo "⚠️  ngrok 安装失败，请手动安装"
        echo "   访问: https://ngrok.com/download"
    fi
else
    echo "✅ ngrok 已安装"
fi

echo ""
echo "🎉 所有依赖检查完成！"
echo ""
echo "下一步："
echo "1. 配置飞书应用（参考 FEISHU_BOT_GUIDE.md）"
echo "2. 编辑 feishu_listener.py 填入您的飞书应用配置"
echo "3. 运行: python3 start.py"
