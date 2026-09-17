#!/usr/bin/env python3
"""启动法律操作系统服务"""
import sys
import os
import subprocess
import socket

# 添加后端路径
backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
sys.path.insert(0, backend_dir)

def start_feishu_listener():
    """启动飞书监听器"""
    import subprocess

    listener_script = os.path.join(script_dir, 'feishu_listener.py')
    listener_config = os.path.join(script_dir, 'feishu_config.py')
    explicitly_enabled = os.environ.get('FEISHU_LISTENER_ENABLED', '').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }

    # The legacy webhook listener is a separate Flask process. Starting it with
    # placeholder credentials creates needless memory, a listening port and an
    # extra SQLite database. Existing configured installations still start it;
    # environment opt-in supports non-file based deployments.
    if os.path.exists(listener_script) and (os.path.exists(listener_config) or explicitly_enabled):
        print("📡 启动飞书监听器...")
        # 使用 subprocess 启动独立的 Python 进程
        process = subprocess.Popen(
            [sys.executable, listener_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=script_dir
        )
        return process
    if os.path.exists(listener_script):
        print("ℹ️  飞书监听器未配置，跳过独立监听进程")
    return None


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    host = os.environ.get('LEGAL_KB_HOST', '127.0.0.1')

    print(f"🏛️  法律操作系统启动中... http://localhost:{port}")

    # 切换到脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        if sock.connect_ex((host, port)) == 0:
            print(f"❌ 端口 {port} 已被占用，可能还有旧的法律操作系统后端进程在运行。")
            print("   请先退出旧进程后重新运行 start.py。")
            sys.exit(1)

    # 启动飞书监听器
    feishu_process = start_feishu_listener()

    # 启动主服务
    cmd = [
        sys.executable, '-m', 'uvicorn',
        'backend.main:app',
        '--host', host,
        '--port', str(port),
    ]
    # File watching creates an extra process and continuously scans the source
    # tree. Keep it opt-in for development instead of charging every normal run.
    if os.environ.get('LEGAL_KB_DEV_RELOAD', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        cmd.extend(['--reload', '--reload-dir', 'backend'])

    try:
        subprocess.run(cmd)
    finally:
        # 清理飞书监听器进程
        if feishu_process:
            try:
                feishu_process.terminate()
                feishu_process.wait(timeout=5)
            except:
                feishu_process.kill()
