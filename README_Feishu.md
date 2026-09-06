# 飞书访问配置指南

## 🎯 方案：飞书机器人 + ngrok 内网穿透

### 📋 配置步骤

#### 1️⃣ 获取飞书机器人 Webhook

1. 打开飞书，进入一个群聊（或创建测试群）
2. 点击群聊右上角 "..." → "设置" → "群机器人"
3. 点击 "添加机器人"，命名（如"法律操作系统"）
4. 点击"添加"后，**复制 Webhook URL**
5. 将 Webhook URL 填入 `feishu_bot.py` 的 `FEISHU_WEBHOOK_URL` 变量

#### 2️⃣ 安装并启动 ngrok

```bash
# macOS 用户
brew install ngrok

# 或者下载：https://ngrok.com/download
```

启动 ngrok（在项目根目录）：

```bash
ngrok http 8765
```

复制显示的公网地址，例如：`https://abc123.ngrok.io`

#### 3️⃣ 配置访问地址

编辑 `feishu_bot.py`，将 `KB_ACCESS_URL` 替换为您的 ngrok 公网地址：

```python
KB_ACCESS_URL = "https://abc123.ngrok.io"  # 替换为实际的 ngrok 地址
```

#### 4️⃣ 启动知识库服务

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
python3 start.py
```

#### 5️⃣ 发送访问链接到飞书

```bash
python3 feishu_bot.py
```

### 🎉 完成！

现在您就可以在飞书中点击机器人发送的卡片，直接访问您的法律操作系统了！

---

## 🔧 常用命令

### 快速启动（一键脚本）

创建启动脚本：

```bash
#!/bin/bash

echo "🚀 启动知识库服务..."
python3 start.py &
sleep 3

echo "📡 启动内网穿透..."
ngrok http 8765 &
sleep 2

echo "📤 发送访问链接到飞书..."
python3 feishu_bot.py

echo "✅ 启动完成！"
```

保存为 `start_all.sh`，然后执行：

```bash
chmod +x start_all.sh
./start_all.sh
```

### 重启服务

如果 ngrok 地址变更，只需要：
1. 在飞书群聊中重新运行 `python3 feishu_bot.py`
2. 或直接在浏览器中访问新的 ngrok 地址

---

## 💡 注意事项

1. **ngrok 免费版限制**：
   - 地址每次重启后会变化
   - 免费版有速率限制
   - 但完全满足个人使用需求

2. **服务必须运行**：
   - `python3 start.py` 必须持续运行
   - `ngrok http 8765` 必须持续运行
   - 建议使用 `screen` 或 `tmux` 保持后台运行

3. **安全提示**：
   - ngrok 免费版生成的 URL 是公开的
   - 建议在飞书群聊中设置访问权限
   - 或者考虑使用 ngrok 的 Auth Token 功能（免费版支持）

---

## 🚀 进阶：使用 Auth Token 保护访问（可选）

1. 注册 ngrok 账号：https://ngrok.com/signup
2. 获取 Authtoken
3. 配置：

```bash
ngrok config add-authtoken YOUR_AUTH_TOKEN
```

4. 启动时添加密码保护：

```bash
ngrok http 8765 --basic-auth="username:password"
```

这样访问时需要输入用户名和密码，更安全！

---

## ❓ 常见问题

**Q: ngrok 地址每次重启都变，怎么办？**
A: 免费版确实如此。您可以：
- 每次重启后重新运行 `python3 feishu_bot.py` 发送新链接
- 或直接在浏览器中访问新的 ngrok 地址
- 升级到 ngrok 付费版（$9/月）可固定域名

**Q: 飞书收不到消息？**
A: 检查：
- Webhook URL 是否正确复制
- 是否有网络连接
- 查看终端输出的错误信息

**Q: 服务运行正常但访问不了？**
A: 检查：
- ngrok 是否在运行
- 知识库服务是否在运行（端口 8765）
- 防火墙是否阻止连接

---

## 📞 需要帮助？

遇到问题可以：
1. 查看终端错误输出
2. 检查 ngrok 控制台（http://localhost:4040）
3. 确认飞书机器人 Webhook 是否正确

祝使用愉快！🎉
