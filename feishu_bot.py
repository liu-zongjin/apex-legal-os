#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书机器人 - 法律操作系统访问
通过飞书机器人发送访问链接
"""

import requests
import json

# 飞书机器人 Webhook URL（请替换为您的实际 Webhook）
FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxxxxxxxxxxx"

# 您的知识库访问地址（ngrok 生成的公网地址）
KB_ACCESS_URL = "https://your-ngrok-url.ngrok.io"


def send_access_link():
    """发送访问链接到飞书"""

    message = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "📚 法律操作系统"
                },
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "点击下方按钮访问您的法律操作系统"
                    }
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "📖 打开知识库"
                            },
                            "type": "primary",
                            "url": KB_ACCESS_URL
                        },
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "🔄 刷新链接"
                            },
                            "type": "default",
                            "url": KB_ACCESS_URL
                        }
                    ]
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**访问地址：** {KB_ACCESS_URL}\n\n💡 提示：请确保本地服务已启动（运行 start.py）"
                    }
                }
            ]
        }
    }

    try:
        response = requests.post(FEISHU_WEBHOOK_URL, json=message)
        result = response.json()

        if result.get("StatusCode") == 0 or result.get("code") == 0:
            print("✅ 消息发送成功！请检查飞书群聊")
        else:
            print(f"❌ 发送失败：{result}")

    except Exception as e:
        print(f"❌ 发送出错：{e}")


if __name__ == "__main__":
    print("🚀 正在发送访问链接到飞书...")
    send_access_link()
