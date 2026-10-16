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
  echo "请根据上方提示检查登录配置、服务状态或旧进程权限，再重新运行。"
  echo ""
  echo "按回车键关闭窗口。"
  read
  exit "$RESULT"
fi

# restart.py has already authenticated and verified a new process with current
# source. A second unauthenticated probe must not override that result.
echo "重启完成，新服务已通过源码版本校验。"
echo ""
echo "正在打开浏览器..."
open "http://localhost:${PORT:-8000}"

echo ""
echo "按回车键关闭窗口。"
read
