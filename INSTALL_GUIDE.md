# 飞书机器人功能 - 安装和配置指南

## 📋 系统要求

- Python 3.8 或更高版本
- 飞书账号
- 公网访问能力（推荐使用 ngrok）

## 🚀 快速安装

### 步骤 1：安装 Python 依赖

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb

# 安装所有必需的依赖
pip3 install flask requests beautifulsoup4 lxml

# 验证安装
python3 -c "import flask, requests, bs4; print('✅ 依赖安装成功')"
```

### 步骤 2：安装 ngrok（用于公网访问）

```bash
# macOS 用户
brew install ngrok

# 验证安装
ngrok version
```

### 步骤 3：创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 点击"创建应用" → "创建企业自建应用"
3. 填写应用信息：
   - 应用名称：法律操作系统抓取机器人
   - 应用描述：自动抓取文章并保存到知识库
4. 创建成功后，记录：
   - **App ID**（在"凭证与基础信息"页面）
   - **App Secret**（点击"查看"获取）

### 步骤 4：配置飞书应用权限

1. 进入应用 → "权限管理" → "权限配置"
2. 搜索并开通以下权限：
   - ✅ `im:message` - 接收消息
   - ✅ `im:message:send_as_bot` - 发送消息（可选）

3. 进入"事件订阅"页面：
   - 添加事件：`im.message.receive_v1`

### 步骤 5：配置本地应用

运行配置向导：

```bash
python3 setup_feishu.py
```

按照提示输入：
- App ID（格式：`cli_xxxxxxxxxxxxxxxx`）
- App Secret
- Encrypt Key（可选，直接回车跳过）
- Verification Token（可选，直接回车跳过）

配置向导会自动创建 `feishu_config.py` 文件。

### 步骤 6：启动内网穿透

```bash
# 启动 ngrok（映射到 8765 端口）
ngrok http 8765
```

复制显示的公网地址，例如：`https://abc123.ngrok.io`

### 步骤 7：配置飞书事件订阅

1. 回到飞书开放平台
2. 进入"事件订阅"页面
3. 配置请求 URL：`https://your-ngrok-url.ngrok.io/feishu/event`
4. 点击"验证"，飞书会自动验证
5. 验证成功后，点击"启用"

### 步骤 8：启动服务

```bash
# 启动所有服务
python3 start.py
```

您会看到：

```
🏛️  法律操作系统启动中... http://localhost:8765
📡 启动飞书监听器...
✅ 已加载配置文件 feishu_config.py
🤖 飞书机器人监听器启动中...
✅ 没有待处理任务
```

## 🎉 完成！

现在您就可以在飞书中使用机器人了！

## 📱 使用方法

### 在飞书中发送链接

1. 打开飞书，找到您的应用
2. 直接发送文章链接：
   ```
   https://example.com/article/123
   ```
3. 系统会自动：
   - 接收链接
   - 抓取文章内容
   - 保存到知识库
   - 记录处理状态

### 查看抓取的文章

访问：`http://localhost:8765` 或您的 ngrok 公网地址

## 🧪 测试功能

```bash
# 测试抓取功能
python3 test_fetch.py https://example.com/article/123
```

## 📊 监控和日志

### 查看待处理任务

```bash
sqlite3 pending_tasks.db "SELECT * FROM pending_tasks WHERE status = 'pending';"
```

### 查看处理日志

终端会实时显示处理进度：

```
📩 收到新 URL: https://example.com/article/123 (来自 示七某)
📥 处理任务: https://example.com/article/123
   来自用户: 示七某
✅ 成功保存文章: 某某法律文章
```

## 🔧 高级配置

### 手动配置

如果不想使用配置向导，可以手动创建 `feishu_config.py`：

```python
# 飞书应用配置
FEISHU_APP_ID = "cli_xxxxxxxxxxxxxxxx"
FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxx"

# 加密配置（可选）
FEISHU_ENCRYPT_KEY = ""
FEISHU_VERIFICATION_TOKEN = ""

# 服务器配置
SERVER_PORT = 5001

# 数据库配置
PENDING_TASKS_DB = "pending_tasks.db"
KB_DB = "legal_kb.db"

# 抓取配置
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 处理配置
PROCESS_DELAY = 1
```

### 自定义抓取规则

编辑 `feishu_listener.py` 中的 `extract_article_content` 函数：

```python
# 添加自定义选择器
content_selectors = [
    'article',
    '.your-custom-selector',
    # ...
]
```

## ⚠️ 常见问题

### Q: 飞书收不到消息？

**A:** 检查以下内容：
1. 飞书应用的事件订阅 URL 是否正确
2. ngrok 是否正在运行
3. 本地服务是否已启动
4. 查看终端日志

### Q: 抓取失败？

**A:** 可能的原因：
1. 网站需要登录
2. 网站有反爬虫机制
3. 网络连接问题
4. URL 格式不正确

**解决方法：**
1. 先用 `python3 test_fetch.py` 测试该 URL
2. 查看错误日志
3. 考虑自定义抓取规则

### Q: 积压任务未处理？

**A:** 重启服务：

```bash
python3 start.py
```

系统会在启动 5 秒后自动处理所有积压任务。

### Q: ngrok 地址每次都变？

**A:** 免费版确实如此。您可以：
1. 每次重启后在飞书重新配置
2. 或升级到 ngrok 付费版（$9/月）

## 📚 更多文档

- **快速开始**: [README_Feishu_AutoFetch.md](./README_Feishu_AutoFetch.md)
- **详细配置指南**: [FEISHU_BOT_GUIDE.md](./FEISHU_BOT_GUIDE.md)
- **飞书开放平台**: https://open.feishu.cn/

## 🆘 需要帮助？

如果遇到问题：
1. 查看终端日志
2. 检查配置文件 `feishu_config.py`
3. 参考详细文档 [FEISHU_BOT_GUIDE.md](./FEISHU_BOT_GUIDE.md)
4. 检查飞书开放平台的应用配置

---

祝使用愉快！🎉
