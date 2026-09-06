#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书机器人监听器
接收用户发送的文章链接，自动抓取并存储到知识库
"""

import json
import time
import requests
import sqlite3
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
import threading
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import re

app = Flask(__name__)

# 加载配置
try:
    from feishu_config import (
        FEISHU_APP_ID,
        FEISHU_APP_SECRET,
        FEISHU_ENCRYPT_KEY,
        FEISHU_VERIFICATION_TOKEN,
        SERVER_PORT,
        PENDING_TASKS_DB,
        KB_DB,
        REQUEST_TIMEOUT,
        USER_AGENT,
        PROCESS_DELAY
    )
    print("✅ 已加载配置文件 feishu_config.py")
except ImportError:
    print("⚠️  未找到配置文件，使用默认配置")
    print("   请参考 feishu_config_template.py 创建配置文件")
    FEISHU_APP_ID = "cli_xxxxxxxxxxxxxxxx"
    FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxx"
    FEISHU_ENCRYPT_KEY = ""
    FEISHU_VERIFICATION_TOKEN = ""
    SERVER_PORT = 5001
    PENDING_TASKS_DB = "pending_tasks.db"
    KB_DB = "legal_kb.db"
    REQUEST_TIMEOUT = 30
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    PROCESS_DELAY = 1

# 获取数据库完整路径
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, PENDING_TASKS_DB)
KB_DB_PATH = os.path.join(BASE_DIR, KB_DB)


class PendingTasksDB:
    """待处理任务数据库管理"""

    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                user_id TEXT,
                user_name TEXT,
                message_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                error_message TEXT
            )
        ''')

        conn.commit()
        conn.close()

    def add_task(self, url, user_id, user_name, message_id):
        """添加待处理任务"""
        # 生成任务 ID（基于 URL 的哈希）
        task_id = hashlib.md5(f"{url}_{user_id}_{int(time.time())}".encode()).hexdigest()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO pending_tasks (task_id, url, user_id, user_name, message_id, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            ''', (task_id, url, user_id, user_name, message_id))
            conn.commit()
            return task_id
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()

    def get_pending_tasks(self, limit=None):
        """获取待处理任务"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM pending_tasks WHERE status = 'pending' ORDER BY created_at ASC"
        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        tasks = cursor.fetchall()
        conn.close()

        return [
            {
                'id': t[0],
                'task_id': t[1],
                'url': t[2],
                'user_id': t[3],
                'user_name': t[4],
                'message_id': t[5],
                'status': t[6],
                'created_at': t[7],
                'processed_at': t[8],
                'error_message': t[9]
            }
            for t in tasks
        ]

    def update_task_status(self, task_id, status, error_message=None):
        """更新任务状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if error_message:
            cursor.execute('''
                UPDATE pending_tasks
                SET status = ?, processed_at = CURRENT_TIMESTAMP, error_message = ?
                WHERE task_id = ?
            ''', (status, error_message, task_id))
        else:
            cursor.execute('''
                UPDATE pending_tasks
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            ''', (status, task_id))

        conn.commit()
        conn.close()


def extract_article_content(url):
    """从 URL 抓取文章内容"""

    headers = {
        'User-Agent': USER_AGENT
    }

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, 'html.parser')

        # 提取标题
        title = soup.find('h1')
        if not title:
            title = soup.find('title')
        title = title.get_text().strip() if title else url

        # 提取正文
        # 尝试多种选择器
        content_selectors = [
            'article',
            '.article-content',
            '.post-content',
            '.entry-content',
            '.content',
            '[class*="article"]',
            '[class*="post"]',
            'main',
            'body'
        ]

        content = None
        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                # 移除脚本、样式等无用标签
                for tag in content_elem.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                    tag.decompose()

                # 提取文本
                content = content_elem.get_text(separator='\n', strip=True)
                if len(content) > 100:  # 确保内容足够长
                    break

        if not content:
            content = soup.get_text(separator='\n', strip=True)

        # 清理内容
        content = re.sub(r'\n{3,}', '\n\n', content)  # 移除多余的空行
        content = content.strip()

        # 提取来源域名
        domain = urlparse(url).netloc

        return {
            'title': title,
            'content': content,
            'source': domain,
            'url': url
        }

    except Exception as e:
        raise Exception(f"抓取失败: {str(e)}")


def save_to_kb(article_data):
    """保存文章到知识库数据库"""

    conn = sqlite3.connect(KB_DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO articles (title, content, source, url, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            article_data['title'],
            article_data['content'],
            article_data['source'],
            article_data['url'],
            datetime.now().isoformat()
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # 可能已存在
    except Exception as e:
        raise e
    finally:
        conn.close()


def process_task(task):
    """处理单个任务"""
    task_db = PendingTasksDB(DB_PATH)

    try:
        print(f"📥 处理任务: {task['url']}")
        print(f"   来自用户: {task['user_name']}")

        # 抓取内容
        article_data = extract_article_content(task['url'])

        # 保存到知识库
        save_to_kb(article_data)

        # 更新任务状态
        task_db.update_task_status(task['task_id'], 'completed')

        print(f"✅ 成功保存文章: {article_data['title']}")
        return True

    except Exception as e:
        error_msg = str(e)
        print(f"❌ 处理失败: {error_msg}")
        task_db.update_task_status(task['task_id'], 'failed', error_msg)
        return False


def process_pending_tasks():
    """处理所有待处理任务"""
    task_db = PendingTasksDB(DB_PATH)
    tasks = task_db.get_pending_tasks()

    if not tasks:
        print("✅ 没有待处理任务")
        return

    print(f"📋 发现 {len(tasks)} 个待处理任务")

    success_count = 0
    failed_count = 0

    for task in tasks:
        if process_task(task):
            success_count += 1
        else:
            failed_count += 1
        time.sleep(PROCESS_DELAY)  # 使用配置的延迟时间

    print(f"\n📊 处理完成: 成功 {success_count} 个, 失败 {failed_count} 个")


def process_url_from_message(message_text, user_id, user_name, message_id):
    """从消息中提取 URL 并添加到待处理队列"""
    # 提取 URL
    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
    urls = re.findall(url_pattern, message_text)

    if not urls:
        return None, "未找到有效的 URL"

    # 只处理第一个 URL
    url = urls[0]
    if url.startswith('www.'):
        url = 'http://' + url

    task_db = PendingTasksDB(DB_PATH)
    task_id = task_db.add_task(url, user_id, user_name, message_id)

    if task_id:
        return url, None
    else:
        return None, "任务已存在或添加失败"


# ========== Flask 路由 ==========

@app.route('/feishu/event', methods=['POST'])
def handle_feishu_event():
    """处理飞书事件推送"""

    data = request.json

    # 处理 URL 验证
    if data.get('type') == 'url_verification':
        return jsonify({
            'challenge': data.get('challenge')
        })

    # 处理消息事件
    if data.get('type') == 'event_callback':
        event = data.get('event', {})
        event_type = event.get('type')

        if event_type == 'im.message.receive_v1':
            # 新消息事件
            message = event.get('message', {})
            message_type = message.get('message_type')
            content = json.loads(message.get('content', '{}'))

            sender = event.get('sender', {})
            user_id = sender.get('sender_id', {}).get('user_id', '')
            user_name = sender.get('sender_id', {}).get('user_name', '未知用户')
            message_id = message.get('message_id', '')

            if message_type == 'text':
                # 文本消息，提取 URL
                text_content = content.get('text', '')
                url, error = process_url_from_message(text_content, user_id, user_name, message_id)

                if url:
                    print(f"📩 收到新 URL: {url} (来自 {user_name})")
                    # 可选：发送确认消息
                    # send_reply_message(message_id, f"已收到链接，正在处理: {url}")
                elif error:
                    print(f"⚠️  消息处理: {error}")

    return jsonify({
        'code': 0,
        'msg': 'success'
    })


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({'status': 'ok'})


# ========== 主程序 ==========

if __name__ == '__main__':
    print("🤖 飞书机器人监听器启动中...")

    # 初始化数据库
    task_db = PendingTasksDB(DB_PATH)

    # 后台线程处理积压任务
    def background_processor():
        time.sleep(5)  # 等待 5 秒后开始处理
        process_pending_tasks()

    processor_thread = threading.Thread(target=background_processor, daemon=True)
    processor_thread.start()

    # 启动 Flask 服务
    app.run(host=os.environ.get('FEISHU_LISTENER_HOST', '127.0.0.1'), port=SERVER_PORT, debug=False)
