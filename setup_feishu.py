#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书配置向导
交互式配置飞书应用
"""

import os
import sys

def setup_feishu_config():
    """交互式配置飞书应用"""

    print("=" * 60)
    print("🤖 飞书机器人配置向导")
    print("=" * 60)
    print()

    # 检查是否已存在配置文件
    config_file = "feishu_config.py"
    if os.path.exists(config_file):
        print(f"⚠️  配置文件 {config_file} 已存在")
        choice = input("是否要重新配置？(y/n): ").strip().lower()
        if choice != 'y':
            print("已取消配置")
            return

    print("请准备以下信息：")
    print("  1. 飞书应用的 App ID")
    print("  2. 飞书应用的 App Secret")
    print("     （在飞书开放平台：https://open.feishu.cn/）")
    print()

    # 获取 App ID
    app_id = input("请输入 App ID (cli_xxxxxxxxxxxxxxxx): ").strip()
    if not app_id:
        print("❌ App ID 不能为空")
        sys.exit(1)

    # 获取 App Secret
    app_secret = input("请输入 App Secret: ").strip()
    if not app_secret:
        print("❌ App Secret 不能为空")
        sys.exit(1)

    # 可选配置
    encrypt_key = input("Encrypt Key (可选，直接回车跳过): ").strip()
    verify_token = input("Verification Token (可选，直接回车跳过): ").strip()

    # 生成配置文件
    config_content = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书配置文件
由 setup_feishu.py 自动生成
"""

# 飞书应用配置
FEISHU_APP_ID = "{app_id}"
FEISHU_APP_SECRET = "{app_secret}"

# 加密配置（可选）
FEISHU_ENCRYPT_KEY = "{encrypt_key}"
FEISHU_VERIFICATION_TOKEN = "{verify_token}"

# 服务器配置
SERVER_PORT = 5001  # 飞书监听器端口

# 数据库配置
PENDING_TASKS_DB = "pending_tasks.db"
KB_DB = "legal_kb.db"

# 抓取配置
REQUEST_TIMEOUT = 30  # 请求超时时间（秒）
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 处理配置
PROCESS_DELAY = 1  # 处理任务之间的延迟（秒）
'''

    # 写入配置文件
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(config_content)

    print()
    print("✅ 配置文件已创建: feishu_config.py")
    print()
    print("📋 下一步：")
    print("  1. 确保知识库服务可以公网访问（使用 ngrok）")
    print("  2. 在飞书开放平台配置事件订阅 URL：")
    print(f"     https://your-ngrok-url.ngrok.io/feishu/event")
    print("  3. 启动服务: python3 start.py")
    print()
    print("💡 提示：您可以随时编辑 feishu_config.py 修改配置")
    print()


if __name__ == '__main__':
    try:
        setup_feishu_config()
    except KeyboardInterrupt:
        print("\n\n已取消配置")
        sys.exit(0)
