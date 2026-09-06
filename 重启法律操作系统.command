#!/bin/zsh

clear
echo "======================================"
echo "       法律操作系统 - 一键重启"
echo "======================================"
echo ""
echo "正在重启法律操作系统服务，请稍等..."
echo ""

cd "$(dirname "$0")" || {
  echo "无法进入法律操作系统文件夹。"
  echo "请确认这个文件仍然放在 legal-kb 文件夹里。"
  echo ""
  echo "按回车键关闭窗口。"
  read
  exit 1
}

PYTHON_BIN="/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.8/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "没有找到 python3，无法启动法律操作系统。"
  echo "请先安装或修复 Python。"
  echo ""
  echo "按回车键关闭窗口。"
  read
  exit 1
fi

"$PYTHON_BIN" restart.py
RESULT=$?

echo ""
if [ "$RESULT" -ne 0 ]; then
  echo "重启没有成功。"
  echo ""
  echo "最常见原因：旧的法律操作系统服务没有权限自动关闭。"
  echo "请按下面步骤处理："
  echo ""
  echo "1. 打开“活动监视器”"
  echo "2. 搜索 python 或 uvicorn"
  echo "3. 选中法律操作系统相关进程，点击左上角 × 强制退出"
  echo "4. 再双击这个“重启法律操作系统.command”文件"
  echo ""
  echo "按回车键关闭窗口。"
  read
  exit "$RESULT"
fi

echo "正在检查服务是否已经恢复..."
sleep 2

HTTP_CODE="$(curl -s -o /tmp/legal_kb_restart_check.txt -w "%{http_code}" http://127.0.0.1:8000/api/server-status)"

if [ "$HTTP_CODE" = "200" ]; then
  echo ""
  echo "重启完成。法律操作系统已经可以使用。"
  echo ""
  echo "正在打开浏览器..."
  open "http://localhost:8000"
else
  echo ""
  echo "服务已尝试启动，但暂时还没有响应。"
  echo "你可以等待 10 秒后刷新浏览器，或再运行一次这个重启脚本。"
fi

echo ""
echo "按回车键关闭窗口。"
read
