#!/usr/bin/env python3
"""
法律操作系统 - 打包启动入口
供 PyInstaller 使用，处理资源路径并启动 uvicorn 服务
"""
import sys
import os
import threading
import webbrowser
import time

# ─── PyInstaller 资源路径适配 ───────────────────────────────────────
def resource_path(relative_path):
    """获取资源的绝对路径，兼容 PyInstaller 打包后的环境"""
    if hasattr(sys, '_MEIPASS'):
        # 打包后：资源在临时解压目录
        base_path = sys._MEIPASS
    else:
        # 开发时：资源在脚本目录
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# ─── 数据目录（打包后放在可执行文件旁边，可持久保存数据）──────────────
def data_path(relative_path):
    """获取数据文件路径（始终在可执行文件旁，不进入临时目录）"""
    if hasattr(sys, '_MEIPASS'):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(exe_dir, relative_path)

# ─── 设置环境变量，让 main.py 知道资源路径 ──────────────────────────
os.environ['LEGAL_KB_RESOURCE_DIR'] = resource_path('.')
os.environ['LEGAL_KB_DATA_DIR'] = data_path('.')

# ─── 切换工作目录到资源目录 ───────────────────────────────────────
if hasattr(sys, '_MEIPASS'):
    os.chdir(sys._MEIPASS)
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

PORT = int(os.environ.get('PORT', '8000'))
HOST = os.environ.get('LEGAL_KB_HOST', '127.0.0.1')

def open_browser():
    """延迟 2 秒后自动打开浏览器"""
    time.sleep(2)
    webbrowser.open(f'http://localhost:{PORT}')

if __name__ == '__main__':
    print("=" * 50)
    print("  法律操作系统")
    print(f"  访问地址: http://localhost:{PORT}")
    print("  关闭此窗口即可停止服务")
    print("=" * 50)

    # 自动打开浏览器
    t = threading.Thread(target=open_browser, daemon=True)
    t.start()

    # 启动 uvicorn
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        log_level="warning",   # 减少日志输出，让界面更干净
    )
