# 飞书机器人自动抓取文章功能 - 快速指南

## 🎯 功能简介

这个功能允许您在飞书中向机器人发送任意文章链接，系统会自动抓取并保存到您的法律操作系统中。**即使 WorkBuddy 未启动，下次启动时也会自动处理所有积压的链接。**

## 📦 已创建的文件

```
legal-kb/
├── feishu_listener.py           # 飞书机器人监听器（核心）
├── feishu_config_template.py    # 配置文件模板
├── setup_feishu.py              # 配置向导（推荐使用）
├── test_fetch.py                # 抓取测试工具
├── start.py                     # 已更新，支持自动启动监听器
├── start_all.sh                 # 一键启动脚本
├── install_dependencies.sh      # 依赖安装脚本
├── FEISHU_BOT_GUIDE.md          # 详细配置指南
└── README_Feishu_AutoFetch.md   # 本文件
```

## 🚀 快速开始（5 分钟）

### 1️⃣ 安装依赖（2 分钟）

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb

# 自动安装所有依赖
bash install_dependencies.sh
```

### 2️⃣ 配置飞书应用（2 分钟）

```bash
# 运行配置向导
python3 setup_feishu.py
```

按照提示输入您的飞书应用信息（App ID 和 App Secret）。

**还没有飞书应用？** [点击这里创建](https://open.feishu.cn/)

### 3️⃣ 启动服务（1 分钟）

```bash
# 方式 1：一键启动（推荐）
bash start_all.sh

# 方式 2：手动启动
python3 start.py
```

## 📱 如何使用

### 在飞书中发送链接

1. 打开飞书，找到您的应用
2. 直接发送文章链接：
   ```
   https://example.com/article/123
   ```
   或附带文字：
   ```
   请抓取：https://example.com/article/123
   ```

3. 系统会自动处理并保存到知识库

### 查看抓取的文章

访问：`http://localhost:8765`

### 测试抓取功能

```bash
# 测试抓取指定 URL
python3 test_fetch.py https://example.com/article/123

# 或交互式测试
python3 test_fetch.py
```

## 🔄 离线/离线场景

### 场景 1：WorkBuddy 未运行

1. 您在飞书中发送链接
2. 飞书会将请求发送到您的服务器
3. 如果 WorkBuddy 未运行，链接会被保存到 `pending_tasks.db`
4. 下次启动 WorkBuddy 时，会自动处理所有积压任务

### 场景 2：批量发送链接

您可以一次性发送多个链接（每行一个），系统会依次处理。

## 📊 监控和日志

### 查看处理状态

```bash
# 查看所有待处理任务
sqlite3 pending_tasks.db "SELECT * FROM pending_tasks WHERE status = 'pending';"

# 查看失败的任务
sqlite3 pending_tasks.db "SELECT url, error_message FROM pending_tasks WHERE status = 'failed';"
```

### 查看终端日志

启动服务后，终端会实时显示：

```
🤖 飞书机器人监听器启动中...
📋 发现 3 个待处理任务
📥 处理任务: https://example.com/article1
   来自用户: 示七某
✅ 成功保存文章: 某某法律文章
```

## 🛠️ 高级配置

### 自定义配置

编辑 `feishu_config.py`：

```python
# 调整抓取超时时间
REQUEST_TIMEOUT = 60  # 秒

# 调整处理间隔
PROCESS_DELAY = 2  # 秒

# 自定义 User-Agent
USER_AGENT = "Mozilla/5.0 (Your Custom User Agent)"
```

### 自定义抓取规则

编辑 `feishu_listener.py` 中的 `extract_article_content` 函数：

```python
# 添加自定义的内容选择器
content_selectors = [
    'article',
    '.your-custom-selector',  # 添加您的选择器
    # ...
]
```

## 🔧 故障排查

### 问题 1：飞书收不到消息

**解决方案：**
1. 检查飞书应用的事件订阅 URL 是否正确
2. 确认 ngrok 正在运行
3. 查看终端日志

### 问题 2：抓取失败

**可能原因：**
- 网站需要登录
- 网站有反爬虫机制
- 网络连接问题

**解决方案：**
1. 先用 `python3 test_fetch.py` 测试该 URL
2. 检查错误日志
3. 考虑自定义抓取规则

### 问题 3：积压任务未处理

**解决方案：**
1. 重启服务：`python3 start.py`
2. 手动触发处理（参考 FEISHU_BOT_GUIDE.md）

## 📚 详细文档

- **完整配置指南**: [FEISHU_BOT_GUIDE.md](./FEISHU_BOT_GUIDE.md)
- **飞书开放平台**: https://open.feishu.cn/

## 💡 使用技巧

1. **批量导入**: 可以一次发送多个链接（每行一个）
2. **URL 验证**: 系统会自动验证 URL 格式
3. **去重**: 相同的 URL 不会重复抓取
4. **错误重试**: 失败的任务会记录错误信息，方便排查

## 🎉 完成！

现在您就可以在飞书中随时发送文章链接，系统会自动帮您抓取并保存到知识库了！

**即使 WorkBuddy 未启动，下次启动时也会自动处理所有积压的链接。**

---

需要帮助？查看 [FEISHU_BOT_GUIDE.md](./FEISHU_BOT_GUIDE.md) 获取更多详细信息。
