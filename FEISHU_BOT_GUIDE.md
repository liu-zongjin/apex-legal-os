# 飞书机器人自动抓取文章功能

## 📋 功能说明

这个功能允许您在飞书中向 WorkBuddy 机器人（或包含机器人的群组）发送文章链接，系统会自动：
1. 接收您发送的文章链接
2. 自动抓取文章内容（标题、正文、来源）
3. 保存到您的法律操作系统中
4. 如果 WorkBuddy 未启动，下次启动时会自动处理积压的链接

## 🚀 快速开始

### 第一步：创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 点击"创建应用" → 选择"创建企业自建应用"
3. 填写应用信息：
   - 应用名称：法律操作系统抓取机器人
   - 应用描述：自动抓取文章并保存到知识库
4. 创建后，记录以下信息：
   - `App ID`：在"凭证与基础信息"页面
   - `App Secret`：点击"查看"获取

### 第二步：配置应用权限

1. 进入应用 → "权限管理" → "权限配置"
2. 搜索并开通以下权限：
   - `im:message`：接收消息
   - `im:message:send_as_bot`：发送消息（可选，用于回复确认）

3. 进入"事件订阅"页面：
   - 添加事件：`im.message.receive_v1`（接收消息事件）

### 第三步：配置服务器地址

您需要一个公网可访问的服务器地址来接收飞书的回调。

**方案 A：使用 ngrok（推荐，免费）**

```bash
# 安装 ngrok
brew install ngrok

# 启动内网穿透（映射到 5001 端口）
ngrok http 5001
```

复制显示的公网地址，例如：`https://abc123.ngrok.io`

**方案 B：使用已有服务器**

如果您有公网服务器，使用以下配置。

### 第四步：配置飞书应用

1. 在飞书开放平台中，进入您的应用
2. 进入"事件订阅"页面
3. 配置请求 URL：`https://your-ngrok-url.ngrok.io/feishu/event`
4. 点击"验证"，飞书会发送验证请求
5. 配置成功后，点击"启用"事件订阅

### 第五步：配置本地应用

编辑 `feishu_listener.py`，填入您的配置：

```python
# 飞书应用配置
FEISHU_APP_ID = "cli_xxxxxxxxxxxxxxxx"  # 您的 App ID
FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxx"  # 您的 App Secret
FEISHU_ENCRYPT_KEY = ""  # 加密密钥（如果需要）
FEISHU_VERIFICATION_TOKEN = ""  # 验证令牌（如果需要）
```

### 第六步：启动服务

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb

# 启动服务（会自动启动飞书监听器）
python3 start.py
```

## 📱 使用方法

### 在飞书中使用

1. 打开飞书，找到您的应用或添加机器人的群组
2. 直接发送文章链接，例如：
   ```
   https://example.com/article/123
   ```
   或附带文字：
   ```
   请抓取这篇文章：https://example.com/article/123
   ```

3. 系统会自动：
   - 接收链接
   - 抓取文章内容
   - 保存到知识库
   - 记录处理状态

### 查看抓取的文章

启动知识库服务后，访问：`http://localhost:8765`，您会看到新抓取的文章。

## 💾 数据持久化

### 待处理任务数据库

系统使用 `pending_tasks.db` 存储所有待处理的抓取任务：

- 如果 WorkBuddy 未运行，链接会被保存到数据库
- 下次启动时，系统会自动处理所有积压任务
- 任务状态：`pending`（待处理）、`completed`（已完成）、`failed`（失败）

### 查看待处理任务

```bash
# 连接数据库查看
sqlite3 pending_tasks.db

# 查询所有任务
SELECT * FROM pending_tasks;

# 查看待处理任务
SELECT * FROM pending_tasks WHERE status = 'pending';

# 查询失败任务
SELECT * FROM pending_tasks WHERE status = 'failed';
```

## 🔧 高级配置

### 手动处理积压任务

如果需要手动触发处理：

```bash
# 创建处理脚本
cat > process_pending.py << 'EOF'
from feishu_listener import process_pending_tasks
process_pending_tasks()
EOF

# 运行
python3 process_pending.py
```

### 自定义抓取规则

编辑 `feishu_listener.py` 中的 `extract_article_content` 函数：

```python
# 添加自定义的内容选择器
content_selectors = [
    'article',
    '.article-content',
    '.custom-selector',  # 添加您的选择器
    # ...
]
```

### 设置抓取频率限制

为了避免请求过快被封，可以调整延迟：

```python
# 在 process_pending_tasks 函数中
time.sleep(2)  # 增加到 2 秒
```

## 📊 监控和日志

### 查看处理日志

启动服务后，终端会显示：

```
🤖 飞书机器人监听器启动中...
📋 发现 3 个待处理任务
📥 处理任务: https://example.com/article1
   来自用户: 示七某
✅ 成功保存文章: 某某法律文章
📥 处理任务: https://example.com/article2
   来自用户: 李四
❌ 处理失败: 抓取失败: Connection timeout
```

### 查看失败任务

```bash
sqlite3 pending_tasks.db "SELECT url, error_message FROM pending_tasks WHERE status = 'failed';"
```

## 🛡️ 安全建议

1. **使用环境变量存储密钥**：
   ```python
   import os
   FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID')
   ```

2. **限制访问来源**：
   - 在飞书中只添加可信的用户到群组
   - 不要公开应用的 Webhook 地址

3. **设置超时和重试**：
   - 避免长时间等待无响应的网站
   - 可以添加重试机制

## ❓ 常见问题

**Q: 为什么有些文章抓取失败？**

A: 可能的原因：
- 网站需要登录才能访问
- 网站有反爬虫机制
- 网络连接问题
- 页面结构特殊，需要自定义抓取规则

**Q: 如何处理需要登录的网站？**

A: 可以扩展 `extract_article_content` 函数，添加 cookie 或 session 支持。

**Q: 积压任务太多怎么办？**

A: 系统会按时间顺序处理，您也可以修改代码并行处理多个任务。

**Q: 如何避免重复抓取？**

A: 系统会根据 URL 和用户 ID 生成唯一任务 ID，相同的链接不会重复添加。

## 🎉 完成！

现在您就可以在飞书中随时发送文章链接，系统会自动帮您抓取并保存到知识库了！

即使 WorkBuddy 未启动，下次启动时会自动处理所有积压的链接。
