#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法答网自动检查更新脚本
每周一上午9点自动检查是否有新增答问，如有则重新抓取并发送飞书通知
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import sys

# 请求头
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

# 法答网精选答问搜索页URL（官方列表页）
SEARCH_URL = 'https://www.court.gov.cn/search.html?content=法答网精选答问'

# 飞书机器人Webhook地址（需要用户配置）
FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/d31124aa-3e71-4c90-a5c8-05818375e5d1'

def send_feishu_notification(title, content, is_update=False):
    """发送飞书通知"""
    if not FEISHU_WEBHOOK:
        print("未配置飞书Webhook地址，跳过通知发送")
        print(f"通知内容：{title}\n{content}")
        return False

    # 根据是否更新设置不同颜色
    color = "blue" if is_update else "gray"
    emoji = "🔔" if is_update else "ℹ️"

    data = {
        "msg_type": "interactive",
        "card": {
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content
                    }
                }
            ],
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{emoji} {title}"
                },
                "template": color
            }
        }
    }

    try:
        response = requests.post(FEISHU_WEBHOOK, json=data, timeout=10)
        if response.status_code == 200:
            print(f"飞书通知已发送")
            return True
        else:
            print(f"飞书通知发送失败: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"飞书通知发送异常: {e}")
        return False

def get_latest_batch_from_web():
    """从官网获取最新一批答问的标题和链接"""
    try:
        print("正在访问法答网搜索页...")
        response = requests.get(SEARCH_URL, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')

        # 尝试查找搜索结果中的答问链接
        latest_title = None
        latest_url = None

        # 搜索结果通常在特定的结构中
        # 尝试多种可能的选择器
        selectors = [
            'a[href*="/zixun/xiangqing/"]',  # 包含法答网链接的a标签
            '.search-result a',
            '.result-list a',
            '.news-list a',
            'ul li a'
        ]

        for selector in selectors:
            links = soup.select(selector)
            if links:
                # 找到第一个包含"法答网精选答问"的链接
                for link in links:
                    href = link.get('href', '')
                    title = link.get_text(strip=True)
                    
                    # 检查是否是法答网链接
                    if '法答网精选答问' in title and '/zixun/xiangqing/' in href:
                        # 构造完整URL
                        if href.startswith('/'):
                            latest_url = 'https://www.court.gov.cn' + href
                        elif href.startswith('http'):
                            latest_url = href
                        else:
                            continue

                        latest_title = title
                        print(f"从官网找到最新批次: {latest_title}")
                        print(f"链接: {latest_url}")
                        return latest_title, latest_url

        # 如果搜索页无法解析，使用已知的最新批次链接作为fallback
        print("搜索页解析失败，使用已知的最新批次链接")
        print(f"正在检查: https://www.court.gov.cn/zixun/xiangqing/488441.html")
        response = requests.get('https://www.court.gov.cn/zixun/xiangqing/488441.html', headers=headers, timeout=30)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = soup.find('title')
        if title:
            page_title = title.get_text(strip=True)
            latest_title = page_title.replace(' - 中华人民共和国最高人民法院', '').strip()
            latest_url = 'https://www.court.gov.cn/zixun/xiangqing/488441.html'
            print(f"获取到批次: {latest_title}")
            print(f"链接: {latest_url}")
            return latest_title, latest_url

        return None, None

    except Exception as e:
        print(f"获取官网信息失败: {e}")
        print("将使用已知的最新批次链接进行检查...")
        # 尝试访问已知的最新批次
        try:
            response = requests.get('https://www.court.gov.cn/zixun/xiangqing/488441.html', headers=headers, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.find('title')
            if title:
                page_title = title.get_text(strip=True)
                latest_title = page_title.replace(' - 中华人民共和国最高人民法院', '').strip()
                return latest_title, 'https://www.court.gov.cn/zixun/xiangqing/488441.html'
        except:
            pass
        
        return None, None

def load_existing_data():
    """加载已保存的数据"""
    data_file = 'data/fada_wang_data.json'
    if not os.path.exists(data_file):
        return []

    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"读取数据文件失败: {e}")
        return []

def has_new_batch(latest_title, latest_url):
    """检查是否有新批次"""
    if not latest_title or not latest_url:
        print("无法获取官网信息，无法判断是否有更新")
        print("将执行完整爬取以确保数据完整性...")
        return True  # 如果无法判断，执行完整爬取

    existing_data = load_existing_data()

    if not existing_data:
        print("本地无历史数据，视为有更新")
        return True

    # 检查最新批次是否已存在
    for item in existing_data:
        if item['title'] == latest_title:
            print(f"最新批次 '{latest_title}' 已存在于本地数据中")
            return False

    print(f"发现新批次: {latest_title}")
    return True

def run_crawler():
    """执行爬虫脚本"""
    print("=" * 60)
    print("开始执行爬虫...")
    print("=" * 60)

    # 导入爬虫模块并执行
    try:
        # 动态导入
        import importlib.util
        spec = importlib.util.spec_from_file_location("crawl_fada", "crawl_fada.py")
        crawl_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(crawl_module)

        # 执行主函数
        crawl_module.main()
        print("爬虫执行完成")
        return True
    except Exception as e:
        print(f"爬虫执行失败: {e}")
        return False

def get_new_batches_summary():
    """获取新增批次的摘要信息"""
    existing_data = load_existing_data()
    if not existing_data:
        return "首次爬取，所有批次均为新增"

    # 获取最新爬取的数据
    latest_batch = existing_data[0] if existing_data else None
    if latest_batch:
        qa_count = len(latest_batch.get('qa_pairs', []))
        publish_date = latest_batch.get('publish_date', '未知')

        # 计算总共的问答数量
        total_qa = sum(len(item.get('qa_pairs', [])) for item in existing_data)

        return f"""
**最新批次**: {latest_batch['title']}
**发布时间**: {publish_date}
**本批答问数量**: {qa_count}条
**累计答问总数**: {total_qa}条
**原文链接**: {latest_batch['url']}
"""
    return "未获取到新增批次信息"

def main():
    """主函数"""
    print("=" * 60)
    print("法答网自动更新检查")
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 检查是否有新批次
    latest_title, latest_url = get_latest_batch_from_web()
    has_update = has_new_batch(latest_title, latest_url)

    if has_update:
        print("\n检测到新增答问，开始更新...")
        success = run_crawler()

        if success:
            # 获取更新摘要
            summary = get_new_batches_summary()

            # 发送飞书通知
            notification_title = "法答网内容已更新"
            notification_content = f"""检查时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}

✅ 检测到法答网有新增答问，已自动完成更新。

{summary}

请访问搜索页面查看完整内容：https://liuzongjin.gitee.io/fada-wang-search/"""

            send_feishu_notification(notification_title, notification_content, is_update=True)
            print("\n✓ 更新完成并已发送通知")
        else:
            # 发送失败通知
            notification_title = "法答网更新失败"
            notification_content = f"""检查时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}

❌ 检测到法答网有新增答问，但自动更新失败。

错误信息：请查看日志获取详细信息。

建议手动执行更新脚本。"""

            send_feishu_notification(notification_title, notification_content, is_update=False)
            print("\n✗ 更新失败，已发送错误通知")
    else:
        # 获取当前数据的统计信息
        existing_data = load_existing_data()
        current_batch_title = "未知"
        total_qa = 0

        if existing_data:
            current_batch_title = existing_data[0]['title']
            total_qa = sum(len(item.get('qa_pairs', [])) for item in existing_data)

        print(f"\n无新增答问，当前已有 {total_qa} 条答问")

        # 发送无更新通知
        notification_title = "法答网无更新"
        notification_content = f"""检查时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}

ℹ️ 法答网精选答问无新增内容。

当前最新批次：{latest_title if latest_title else current_batch_title}
当前累计答问：{total_qa}条

下次检查时间：下周一、三或五上午9点"""

        send_feishu_notification(notification_title, notification_content, is_update=False)
        print("✓ 已发送无更新通知")

    print("=" * 60)

if __name__ == '__main__':
    main()
