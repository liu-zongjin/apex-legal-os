# 飞书机器人自动抓取功能 - 配置总结

## ✅ 已完成的工作

### 📁 创建的文件

| 文件名 | 说明 | 优先级 |
|--------|------|--------|
| `feishu_listener.py` | 飞书机器人监听器（核心功能） | ⭐⭐⭐ 必需 |
| `feishu_config_template.py` | 配置文件模板 | ⭐⭐⭐ 必需 |
| `setup_feishu.py` | 交互式配置向导 | ⭐⭐⭐ 必需 |
| `test_fetch.py` | 抓取功能测试工具 | ⭐⭐ 推荐 |
| `start.py` | 已更新，支持自动启动监听器 | ⭐⭐⭐ 必需 |
| `start_all.sh` | 一键启动脚本 | ⭐⭐ 推荐 |
| `install_dependencies.sh` | 依赖安装脚本 | ⭐⭐ 推荐 |
| `README_Feishu_AutoFetch.md` | 快速使用指南 | ⭐⭐⭐ 必需 |
| `INSTALL_GUIDE.md` | 详细安装配置指南 | ⭐⭐⭐ 必需 |
| `FEISHU_BOT_GUIDE.md` | 完整功能文档 | ⭐⭐ 推荐 |
| `SETUP_SUMMARY.md` | 本文件 | ⭐⭐ 推荐 |

### 🔧 修改的文件

| 文件名 | 修改内容 |
|--------|----------|
| `start.py` | 添加了自动启动飞书监听器的功能 |

---

## 🚀 下一步操作

### 第 1 步：安装依赖（2 分钟）

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb

# 安装 Python 依赖
pip3 install flask requests beautifulsoup4 lxml

# 验证安装
python3 -c "import flask, requests, bs4; print('✅ 依赖安装成功')"
```

### 第 2 步：配置飞书应用（3 分钟）

**方式 A：使用配置向导（推荐）**

```bash
python3 setup_feishu.py
```

按照提示输入您的飞书应用信息。

**方式 B：手动配置**

1. 复制 `feishu_config_template.py` 为 `feishu_config.py`
2. 编辑 `feishu_config.py`，填入您的配置：
   ```python
   FEISHU_APP_ID = "cli_xxxxxxxxxxxxxxxx"
   FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxx"
   ```

### 第 3 步：创建飞书应用（5 分钟）

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 创建应用 → 记录 App ID 和 App Secret
3. 配置权限：
   - 开通 `im:message` 权限
   - 添加 `im.message.receive_v1` 事件

### 第 4 步：启动内网穿透

```bash
# 安装 ngrok（如果还未安装）
brew install ngrok

# 启动 ngrok
ngrok http 8765
```

复制显示的公网地址，例如：`https://abc123.ngrok.io`

### 第 5 步：配置飞书事件订阅

1. 在飞书开放平台中，进入"事件订阅"页面
2. 配置请求 URL：`https://your-ngrok-url.ngrok.io/feishu/event`
3. 点击"验证"，然后"启用"

### 第 6 步：启动服务

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

### 第 7 步：测试功能

在飞书中向您的应用发送一个文章链接：

```
https://example.com/article/123
```

系统会自动抓取并保存到知识库！

---

## 📱 使用方法

### 在飞书中使用

1. 打开飞书，找到您的应用
2. 直接发送文章链接
3. 系统会自动处理并保存

### 本地测试

```bash
# 测试抓取功能
python3 test_fetch.py https://example.com/article/123
```

### 查看抓取的文章

访问：`http://localhost:8765` 或您的 ngrok 公网地址

---

## 🔄 离线场景支持

### WorkBuddy 未启动时

1. 您在飞书中发送链接
2. 如果 WorkBuddy 未运行，链接会被保存到数据库
3. 下次启动时，系统会自动处理所有积压任务

### 查看待处理任务

```bash
sqlite3 pending_tasks.db "SELECT * FROM pending_tasks WHERE status = 'pending';"
```

---

## 📊 监控和日志

### 查看处理状态

终端会实时显示：

```
📩 收到新 URL: https://example.com/article/123 (来自 示七某)
📥 处理任务: https://example.com/article/123
   来自用户: 示七某
✅ 成功保存文章: 某某某法律文章
```

### 查看数据库

```bash
# 查看所有任务
sqlite3 pending_tasks.db "SELECT * FROM pending_tasks;"

# 查看待处理任务
sqlite3 pending_tasks.db "SELECT * FROM pending_tasks WHERE status = 'pending';"

# 查看失败任务
sqlite3 pending_tasks.db "SELECT url, error_message FROM pending_tasks WHERE status = 'failed';"
```

---

## 📚 文档导航

| 文档 | 说明 | 适合人群 |
|------|------|----------|
| [README_Feishu_AutoFetch.md](./README_Feishu_AutoFetch.md) | 快速开始指南 | 所有用户 |
| [INSTALL_GUIDE.md](./INSTALL_GUIDE.md) | 详细安装配置指南 | 新用户 |
| [FEISHU_BOT_GUIDE.md](./FEISHU_BOT_GUIDE.md) | 完整功能文档 | 高级用户 |

---

## 🎯 功能特性

✅ **自动接收链接** - 在飞书中发送链接即可
✅ **智能抓取** - 自动提取标题、正文、来源
✅ **离线支持** - 未启动时链接会被保存，下次启动时处理
✅ **去重机制** - 相同的 URL 不会重复抓取
✅ **错误处理** - 失败的任务会记录错误信息
✅ **批量处理** - 支持一次发送多个链接
✅ **可扩展** - 支持自定义抓取规则

---

## ⚠️ 注意事项

1. **依赖安装**：确保已安装所有 Python 依赖
2. **ngrok 运行**：必须保持 ngrok 运行才能接收飞书消息
3. **服务启动**：必须启动知识库服务（`python3 start.py`）
4. **配置正确**：确保 `feishu_config.py` 中的配置正确
5. **网络连接**：确保可以访问要抓取的网站

---

## 🔧 故障排查

### 问题：飞书收不到消息

**检查清单：**
- [ ] ngrok 是否在运行
- [ ] 知识库服务是否已启动
- [ ] 飞书事件订阅 URL 是否正确
- [ ] 查看终端日志

### 问题：抓取失败

**检查清单：**
- [ ] URL 是否有效
- [ ] 网站是否需要登录
- [ ] 网络连接是否正常
- [ ] 使用 `python3 test_fetch.py` 测试该 URL

### 问题：积压任务未处理

**解决方法：**
```bash
# 重启服务
python3 start.py
```

---

## 🎉 完成！

现在您就可以在飞书中随时发送文章链接，系统会自动帮您抓取并保存到知识库了！

**即使 WorkBuddy 未启动，下次启动时也会自动处理所有积压的链接。**

---

**需要帮助？** 查看 [INSTALL_GUIDE.md](./INSTALL_GUIDE.md) 获取更多详细信息。
