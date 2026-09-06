# 飞书机器人功能 - 启动指南

## ✅ 问题已修复！

多进程启动错误已修复，现在可以正常启动了。

---

## 🚀 启动服务

### 方式 1：使用 start.py（推荐）

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
python3 start.py
```

这会同时启动：
- ✅ 法律操作系统服务（端口 8765）
- ✅ 飞书监听器（端口 5001）

### 方式 2：分别启动（用于调试）

如果您想分别启动两个服务，可以：

```bash
# 终端 1：启动知识库服务
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload

# 终端 2：启动飞书监听器
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
python3 feishu_listener.py
```

---

## 🔍 验证服务是否正常启动

### 检查知识库服务

```bash
curl http://localhost:8765
```

应该返回 HTML 页面。

### 检查飞书监听器

```bash
curl http://localhost:5001/health
```

应该返回：`{"status":"ok"}`

---

## 📱 配置飞书应用（如果还未配置）

### 1. 填入配置

编辑 `feishu_config.py`：

```bash
open /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb/feishu_config.py
```

填入您的飞书应用信息：

```python
FEISHU_APP_ID = "cli_xxxxxxxxxxxxxxxx"
FEISHU_APP_SECRET = "xxxxxxxxxxxxxxxx"
```

### 2. 创建飞书应用

1. 访问 https://open.feishu.cn/
2. 创建应用 → 创建企业自建应用
3. 获取 App ID 和 App Secret
4. 配置权限：`im:message`
5. 添加事件：`im.message.receive_v1`

### 3. 配置内网穿透（可选）

```bash
# 安装 ngrok
brew install ngrok

# 启动 ngrok
ngrok http 8765
```

复制显示的公网地址，在飞书开放平台配置事件订阅 URL：
`https://your-ngrok-url.ngrok.io/feishu/event`

---

## 🧪 测试功能

### 测试文章抓取（无需飞书配置）

```bash
python3 test_fetch.py https://example.com/article/123
```

### 检查配置

```bash
python3 check_config.py
```

---

## 📊 查看日志

启动服务后，终端会显示：

```
🏛️  法律操作系统启动中... http://localhost:8765
📡 启动飞书监听器...
✅ 已加载配置文件 feishu_config.py
🤖 飞书机器人监听器启动中...
✅ 没有待处理任务
```

---

## 🔧 故障排查

### 问题 1：端口被占用

```bash
# 查看占用端口的进程
lsof -ti:8765
lsof -ti:5001

# 停止进程
kill -9 <PID>
```

### 问题 2：飞书监听器未启动

检查配置文件是否存在且正确：

```bash
cat /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb/feishu_config.py
```

### 问题 3：依赖缺失

```bash
pip3 install flask requests beautifulsoup4 lxml
```

---

## 📚 更多文档

- **详细配置**: [INSTALL_GUIDE.md](./INSTALL_GUIDE.md)
- **快速参考**: [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)
- **最终说明**: [FINAL_INSTRUCTIONS.md](./FINAL_INSTRUCTIONS.md)

---

**现在可以启动服务了！🎉**
