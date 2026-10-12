# Stella / APEX · 法律操作系统

**作者：刘宗锦律师** · 应用公开下载 · 禁止商用 · 禁止修改

[下载 Mac 应用](https://github.com/liu-zongjin/stella-downloads/releases/download/v1.0.0-preview1/Stella-macOS-AppleSilicon-v1.0.0-preview1.zip) · [下载与安装说明](DOWNLOAD.md) · [许可协议](LICENSE)

> 应用安装包在 [公开下载仓库](https://github.com/liu-zongjin/stella-downloads) 分发，本源码仓库保持私有。本项目采用自定义许可证，仅供个人非商业学习、研究与体验；用于律所运营、收费法律服务或修改代码须另行取得作者书面授权。

面向律师与法律团队的**单用户 macOS 混合桌面应用**：原生 AppKit 外壳内嵌 WKWebView，由本地 FastAPI 服务驱动，数据全程保存在本机 SQLite，不依赖云端托管。

```text
Stella.app（AppKit 外壳）
  └─ WKWebView
       ├─ frontend/index.html + app.js + style.css
       ├─ 各功能页以同源 iframe 加载
       └─ HTTP / postMessage / 原生消息桥
              ↕
        FastAPI 本地服务（http://localhost:8000）
          ├─ legal_kb.db（SQLite）
          ├─ 上传文件与案件文件夹
          ├─ AI、邮件、飞书、夸克、法律数据源集成
          └─ 法院网页自动化与后台调度
```

## 核心功能

| 模块 | 说明 |
| --- | --- |
| 案件管理 | 案件、系列案（系列子案主表/公共信息/请求项继承）、开庭提醒、待办、财产保全、上诉异议期；开庭通知 OCR+AI 识别；一键同步 iCloud 日历与 iCloud 通讯录；司法短信台账；法院一张网案件同步 |
| 客户与当事人 | 委托人库、对方当事人库、当事人档案与统一社会信用代码补全 |
| 法院通讯录 | 法院公开通讯录的检索、网页/公众号/照片 OCR 识别与维护 |
| 法律知识库 | 文章库、全文检索、知识拓展、阅读统计与推荐 |
| 文书工具 | 批量文书生成、所函、授权委托书、代表人身份证明书、业务审批表、文书包生成；Word 模板上传与占位符校验 |
| 数据工具 | 利息计算、发票中心、预付费用管理 |
| 办案辅助 | 录音转写、扫描件收件箱、下载中心、自动化立案、名思会议 |
| AI 与集成 | DeepSeek 等大模型接入、MCP 服务管理、QQ 邮箱、飞书机器人 |
| 个人中心 | 效率中心、性能面板（仅进程内聚合指标，不记录请求内容） |

## 快速开始

### 源码运行（macOS）

```bash
# 1. 安装依赖
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-private.txt
npm ci

# 2. 启动（默认端口 8000，可用 PORT 环境变量覆盖）
python3 start.py
# 浏览器访问 http://localhost:8000
```

### 打包为 macOS 应用

```bash
bash build_mac.sh
# 产出 dist/法律操作系统.app 与 dist/法律操作系统_Mac.zip
```

Windows 打包：`build_windows.bat`。

## 目录结构

```text
native-shell/    AppKit 外壳：窗口生命周期、菜单快捷键、通知、下载、生物识别桥、WebKit 恢复
frontend/        表现层：单文件功能页 + 共享组件（apex-*.js / apex-*.css）
backend/         FastAPI 服务：业务 API、SQLite、集成、文书生成、后台任务
tests/           隔离测试（临时数据库与匿名夹具）
docs/            架构与设计文档（SYSTEM_MAP、DESIGN_SYSTEM、API 兼容性、ADR）
scripts/         维护脚本与 apex_guard 质量门禁
legal_kb.db      运行时数据（不入版本库）
```

## 质量门禁

所有改动需通过仓库自检脚本：

```bash
python3 scripts/apex_guard.py preflight   # 变更影响评估
python3 scripts/apex_guard.py fast        # 快速检查（聚焦改动）
python3 scripts/apex_guard.py extended    # 跨模块改动的扩展检查
```

开发约定见 [AGENTS.md](AGENTS.md)：共享能力注册、APEX 风格的自绘控件（不使用原生弹层）、设计令牌、性能预算与隐私边界。

## 相关文档

- [AGENTS.md](AGENTS.md) — 工程规则与变更流程
- [docs/architecture/SYSTEM_MAP.md](docs/architecture/SYSTEM_MAP.md) — 系统架构与边界
- [docs/design/DESIGN_SYSTEM.md](docs/design/DESIGN_SYSTEM.md) — 设计系统
- [docs/architecture/API_COMPATIBILITY.md](docs/architecture/API_COMPATIBILITY.md) — API 兼容性约定
- [docs/architecture/ADR-0001-hybrid-macos-architecture.md](docs/architecture/ADR-0001-hybrid-macos-architecture.md) — 混合架构决策记录
- [CHANGELOG.md](CHANGELOG.md) — 用户可见变更记录

## 隐私与数据安全

- 业务数据（案件、当事人、文书）保存在本机 SQLite 与本地文件夹，不落云端。
- 运行时数据（数据库、上传、日志、密钥）均不进入版本控制；密钥保存在 macOS 钥匙串或本地忽略配置中。
- 性能指标只做进程内聚合，不记录请求体、查询串、当事人名称或文件路径。

## 许可

本项目原创部分采用 [Stella / APEX 源码公开许可协议](LICENSE)：**禁止商用、禁止修改，保留作者署名“刘宗锦律师”**。允许免费阅读、下载、非商业运行原版及完整转发原版副本。第三方材料按其原有许可适用，详见 [第三方权利声明](THIRD_PARTY_NOTICES.md)。

该协议包含非商业与禁止修改限制，属于源码公开许可，不属于 OSI 定义的开源许可。
