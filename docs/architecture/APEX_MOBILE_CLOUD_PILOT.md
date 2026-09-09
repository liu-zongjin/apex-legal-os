# APEX Mobile 匿名云端测试版

## 当前目的

这一套配置只用于验证手机访问、登录、安装为网页应用、案件管理移动布局、离线缓存和轻量编辑流程。它会创建独立的 `apex-anonymous-pilot.db`，首次启动仅写入名称中明确标注“虚构”的案例、委托人和日程。

它不是生产环境，也不能导入真实案件、委托人、文书、录音、文件、密钥或浏览器会话。GitHub 只保存容器配置和源码，不保存匿名测试运行卷里的数据库。

## 允许与排除的范围

匿名测试可验证：手机查看与搜索虚构案件、委托人和日程；轻量编辑；上传虚构材料；从手机安装 APEX；以及从手机发起不含密钥的 AI 任务入口。

以下能力保持桌面端专用，且测试容器已禁用相关后台任务：法院 Chrome 自动化、司法短信读取、批量文书生成、OCR、真实邮箱与网盘同步、使用真实 AI 密钥的任务，以及对本机的启动、重启和文件管理。

## 隔离与安全约束

- 容器构建上下文由 `.dockerignore` 过滤，不会发送本机数据库、上传文件、浏览器资料、密钥或 `dist/APEX.app`。
- `APEX_ANONYMOUS_PILOT=1` 启动时强制要求独立运行目录，数据库文件必须命名为 `apex-anonymous-pilot.db`，因此不能误指向日常的 `legal_kb.db`。
- 配置里出现外部 API key、授权 token 或 authorization 值时，入口会拒绝启动。访问密码和会话密钥必须由测试者自己生成，示例占位值不能启动。
- 匿名数据库位于 Docker 命名卷 `apex_anonymous_pilot_runtime`。删除该卷即可恢复为全新的虚构数据；不要把该卷复制到日常 APEX 环境。

## 本机无数据演练

在项目根目录执行以下步骤。先确认 Docker Desktop 正在运行；这只会建立匿名容器和命名卷，不会读取日常 APEX 数据。

```bash
cp deploy/mobile-pilot/.env.mobile-pilot.example deploy/mobile-pilot/.env.mobile-pilot.local
# 编辑 .env.mobile-pilot.local，把两个 replace-me 改为不同的随机长字符串。
docker compose -f deploy/mobile-pilot/compose.yaml up --build
```

本机浏览器打开 `http://127.0.0.1:8000`，使用 `.env.mobile-pilot.local` 中设置的账号和密码登录。浏览器从案件管理页打开时可安装为 APEX 网页应用；手机端安装入口将直接进入该页面。

清理本次匿名演练：

```bash
docker compose -f deploy/mobile-pilot/compose.yaml down --volumes
```

## 后续接入免费测试托管

在选择云服务前，本分支已提供可交付的容器。测试托管只需使用同一 Dockerfile、一个持久卷和 HTTPS 域名，并将 `.env.mobile-pilot.local` 的三项值改为托管平台的私密环境变量。平台必须允许容器内的持久化存储；若只提供无状态容器，匿名数据会在重启后丢失，这仍可用于界面测试。

正式使用真实数据前，需单独完成数据存储地区、备案/合规、访问控制、备份与恢复、对象存储、数据库迁移和桌面端同步方案评审。那会是一个新的跨模块变更，不能把真实数据直接放进这个匿名测试容器。
