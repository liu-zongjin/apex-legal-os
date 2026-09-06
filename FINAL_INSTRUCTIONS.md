# 飞书机器人自动抓取功能 - 最终配置说明

## ✅ 已完成的工作

我已经为您实现了完整的飞书机器人自动抓取文章功能！所有必要的文件都已创建，依赖也已安装完成。

### 📁 已创建的文件

| 文件名 | 说明 |
|--------|------|
| `feishu_listener.py` | 飞书机器人监听器（核心） |
| `feishu_config.py` | 配置文件（需要您填入 App ID 和 App Secret） |
| `feishu_config_template.py` | 配置文件模板 |
| `check_config.py` | 配置检查工具 |
| `setup_feishu.py` | 配置向导（交互式，需要手动运行） |
| `test_fetch.py` | 抓取测试工具 |
| `start.py` | 已更新，支持自动启动监听器 |
| `start_all.sh` | 一键启动脚本 |
| `install_dependencies.sh` | 依赖安装脚本 |
| `quick_config.sh` | 快速配置说明脚本 |
| `MANUAL_SETUP.md` | 手动配置指南 |
| `INSTALL_GUIDE.md` | 详细安装配置指南 |
| `README_Feishu_AutoFetch.md` | 快速使用指南 |
| `FEISHU_BOT_GUIDE.md` | 完整功能文档 |
| `SETUP_SUMMARY.md` | 配置总结 |
| `QUICK_REFERENCE.md` | 快速参考卡片 |

### ✅ 已安装的依赖

- ✅ Python 3.8.2
- ✅ Flask
- ✅ Requests
- ✅ BeautifulSoup4
- ✅ lxml

---

## 🚀 下一步操作（只需要 3 步）

### 第 1 步：填入飞书应用配置

编辑配置文件：

```bash
# 使用文本编辑器打开配置文件
open /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb/feishu_config.py
```

或者使用任何编辑器编辑该文件，填入您的飞书应用信息：

```python
# 飞书应用配置
FEISHU_APP_ID = "cli_a1b2c3d4e5f6g7h8"  # 替换为您的 App ID
FEISHU_APP_SECRET = "AbCdEfGhIjKlMnOpQrStUvWxYz123456"  # 替换为您的 App Secret
```

**如何获取 App ID 和 App Secret？**

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 点击"创建应用" → "创建企业自建应用"
3. 填写应用信息：
   - 应用名称：法律操作系统抓取机器人
   - 应用描述：自动抓取文章并保存到知识库
4. 创建成功后：
   - **App ID**：在"凭证与基础信息"页面
   - **App Secret**：点击"查看"获取

### 第 2 步：配置飞书应用权限

1. 进入您的飞书应用
2. 进入"权限管理" → "权限配置"
3. 搜索并开通权限：
   - ✅ `im:message` - 接收消息
4. 进入"事件订阅"页面：
   - 添加事件：`im.message.receive_v1`

### 第 3 步：启动服务

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
python3 start.py
```

---

## 🌐 配置内网穿透（可选但推荐）

如果您想在飞书中接收消息，需要公网访问能力。推荐使用 ngrok：

### 安装 ngrok

```bash
brew install ngrok
```

### 启动 ngrok

打开新的终端窗口：

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
ngrok http 8765
```

复制显示的公网地址，例如：`https://abc123.ngrok.io`

### 配置飞书事件订阅

1. 回到飞书开放平台
2. 进入"事件订阅"页面
3. 配置请求 URL：`https://your-ngrok-url.ngrok.io/feishu/event`
4. 点击"验证"，飞书会自动验证
5. 验证成功后，点击"启用"

---

## 📱 使用方法

配置完成后，在飞书中向您的应用发送文章链接：

```
https://example.com/article/123
```

系统会自动抓取并保存到知识库！

### 查看抓取的文章

访问：`http://localhost:8765` 或您的 ngrok 公网地址

---

## 🧪 测试功能

### 测试配置

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
python3 check_config.py
```

### 测试抓取

```bash
python3 test_fetch.py https://example.com/article/123
```

---

## 🔄 离线场景支持

**场景：WorkBuddy 未启动**

1. 您在飞书中发送链接
2. 飞书会将请求发送到您的服务器
3. 如果 WorkBuddy 未运行，链接会被保存到 `pending_tasks.db`
4. **下次启动 WorkBuddy 时，会自动处理所有积压任务**

### 查看待处理任务

```bash
sqlite3 pending_tasks.db "SELECT * FROM pending_tasks WHERE status = 'pending';"
```

---

## 📚 文档导航

| 文档 | 说明 | 适用场景 |
|------|------|----------|
| [FINAL_INSTRUCTIONS.md](./FINAL_INSTRUCTIONS.md) | 本文件 | 快速配置 |
| [MANUAL_SETUP.md](./MANUAL_SETUP.md) | 手动配置指南 | 详细步骤 |
| [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) | 快速参考卡 | 日常使用 |
| [INSTALL_GUIDE.md](./INSTALL_GUIDE.md) | 完整安装指南 | 首次配置 |
| [FEISHU_BOT_GUIDE.md](./FEISHU_BOT_GUIDE.md) | 功能详解文档 | 高级配置 |

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

## ⚠️ 重要提示

1. **必须填入配置**：编辑 `feishu_config.py` 填入您的飞书应用 App ID 和 App Secret
2. **配置飞书权限**：在飞书开放平台配置 `im:message` 权限
3. **启动服务**：运行 `python3 start.py` 启动服务
4. **公网访问**：如需在飞书中接收消息，需要配置内网穿透（ngrok）

---

## 🆘 需要帮助？

### 快速检查

```bash
# 检查配置是否正确
python3 check_config.py

# 检查依赖是否安装
python3 -m pip list | grep -E "flask|requests|beautifulsoup4|lxml"
```

### 常见问题

**Q: 如何填入配置？**

A: 编辑 `feishu_config.py`，填入：
```python
FEISHU_APP_ID = "cli_xxxxxxxxxxxxxxxx"
FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxx"
```

**Q: 如何获取飞书应用信息？**

A: 访问 https://open.feishu.cn/ 创建应用，在"凭证与基础信息"页面获取。

**Q: 是否需要配置内网穿透？**

A: 如果想在飞书中接收消息，需要配置 ngrok。如果只是本地测试，可以跳过。

**Q: 如何测试功能？**

A: 运行 `python3 test_fetch.py https://example.com/article/123` 测试抓取。

---

## 🎉 完成！

所有代码和配置文件都已准备就绪，您只需要：

1. 编辑 `feishu_config.py` 填入飞书应用配置
2. 在飞书开放平台配置权限
3. 运行 `python3 start.py` 启动服务

然后就可以在飞书中发送文章链接，系统会自动抓取并保存到知识库了！

**即使 WorkBuddy 未启动，下次启动时也会自动处理所有积压的链接。**

---

**祝使用愉快！🎉**
