#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书配置模板
复制此文件为 feishu_config.py 并填入您的实际配置
"""

# 飞书应用配置
FEISHU_APP_ID = "cli_xxxxxxxxxxxxxxxx"  # 替换为您的 App ID
FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxx"  # 替换为您的 App Secret

# 加密配置（可选，用于增强安全性）
FEISHU_ENCRYPT_KEY = ""  # 如果启用了加密，填入 Encrypt Key
FEISHU_VERIFICATION_TOKEN = ""  # 如果启用了验证，填入 Verification Token

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
