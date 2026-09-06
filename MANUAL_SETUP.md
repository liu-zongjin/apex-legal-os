# 飞书配置手动设置指南

由于当前环境不支持交互式输入，请按照以下步骤手动配置：

## 📋 步骤 1：填写飞书配置

编辑文件：`/Users/liuzongjin/WorkBuddy/20260319113739/legal-kb/feishu_config.py`

替换以下内容：

```python
# 飞书应用配置
FEISHU_APP_ID = ""  # 请替换为您的 App ID
FEISHU_APP_SECRET = ""  # 请替换为您的 App Secret
```

例如：

```python
FEISHU_APP_ID = "cli_a1b2c3d4e5f6g7h8"
FEISHU_APP_SECRET = "AbCdEfGhIjKlMnOpQrStUvWxYz123456"
```

## 📋 步骤 2：获取飞书应用信息

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 点击"创建应用" → "创建企业自建应用"
3. 填写应用信息：
   - 应用名称：法律操作系统抓取机器人
   - 应用描述：自动抓取文章并保存到知识库
4. 创建成功后：
   - 在"凭证与基础信息"页面找到 **App ID**
   - 点击 **App Secret** 旁边的"查看"，复制该密钥

## 📋 步骤 3：配置飞书应用权限

1. 进入您的飞书应用
2. 进入"权限管理" → "权限配置"
3. 搜索并开通以下权限：
   - ✅ `im:message` - 接收消息
   - ✅ `im:message:send_as_bot` - 发送消息（可选）

4. 进入"事件订阅"页面：
   - 添加事件：`im.message.receive_v1`

## 📋 步骤 4：安装依赖

在终端中运行：

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
pip3 install flask requests beautifulsoup4 lxml
```

## 📋 步骤 5：启动服务

```bash
python3 start.py
```

## 📋 步骤 6：启动内网穿透

打开新的终端窗口，运行：

```bash
# 如果还未安装 ngrok
brew install ngrok

# 启动 ngrok
ngrok http 8765
```

复制显示的公网地址，例如：`https://abc123.ngrok.io`

## 📋 步骤 7：配置飞书事件订阅

1. 回到飞书开放平台
2. 进入"事件订阅"页面
3. 配置请求 URL：`https://your-ngrok-url.ngrok.io/feishu/event`
4. 点击"验证"，飞书会自动验证
5. 验证成功后，点击"启用"

## 🎉 完成！

现在您就可以在飞书中发送文章链接了！

## 📱 使用方法

在飞书中向您的应用发送文章链接：

```
https://example.com/article/123
```

系统会自动抓取并保存到知识库！

## ❓ 需要帮助？

- 查看详细文档：`/Users/liuzongjin/WorkBuddy/20260319113739/legal-kb/INSTALL_GUIDE.md`
- 查看快速参考：`/Users/liuzongjin/WorkBuddy/20260319113739/legal-kb/QUICK_REFERENCE.md`
