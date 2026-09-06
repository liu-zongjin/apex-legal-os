# 快速参考卡片

## 🚀 一键启动（推荐）

```bash
cd /Users/liuzongjin/WorkBuddy/20260319113739/legal-kb
bash install_dependencies.sh  # 首次运行，安装依赖
python3 setup_feishu.py        # 首次运行，配置飞书应用
python3 start.py               # 启动服务
```

## 📱 使用方法

在飞书中发送文章链接：
```
https://example.com/article/123
```

系统会自动抓取并保存到知识库！

## 🧪 测试功能

```bash
python3 test_fetch.py https://example.com/article/123
```

## 📊 查看待处理任务

```bash
sqlite3 pending_tasks.db "SELECT * FROM pending_tasks WHERE status = 'pending';"
```

## 🔧 配置文件

编辑 `feishu_config.py` 修改配置。

## 📚 文档

- **快速开始**: [README_Feishu_AutoFetch.md](./README_Feishu_AutoFetch.md)
- **详细配置**: [INSTALL_GUIDE.md](./INSTALL_GUIDE.md)
- **完整文档**: [FEISHU_BOT_GUIDE.md](./FEISHU_BOT_GUIDE.md)

---

**需要帮助？** 查看 [INSTALL_GUIDE.md](./INSTALL_GUIDE.md) 或 [SETUP_SUMMARY.md](./SETUP_SUMMARY.md)
