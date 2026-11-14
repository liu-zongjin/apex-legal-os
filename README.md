<div align="center">

# Stella · 法律操作系统

**为律师的日常工作，留一处清晰的空间。**

案件管理、法律知识、文书工具与 AI 辅助，汇聚在一个本地优先的工作空间。

[访问官网](https://liu-zongjin.github.io/stella-downloads/)　·　[下载与安装](https://liu-zongjin.github.io/stella-downloads/download.html)　·　[功能更新](CHANGELOG.md)　·　[反馈问题](https://github.com/liu-zongjin/apex-legal-os/issues)

原创源码采用 [AGPL-3.0-only](LICENSE) · 作者：刘宗锦律师（LIU Zongjin）

</div>

## Stella 能做什么

Stella 面向律师和法律工作者，将办案资料、知识与常用工具放在同一个工作空间，减少在多个应用之间切换。项目以单用户本地使用为主；案件、知识和附件保存在使用者自己的电脑上。

| 工作场景 | 主要功能 |
| --- | --- |
| **管理案件** | 管理案件和系列案、当事人、开庭与期限提醒、待办、财产保全及案件文件；支持识别开庭通知、管理司法短信和对接法院一张网。 |
| **积累知识** | 收集和检索法律文章，整理阅读笔记；使用 AI 辅助知识拓展、排版与公开类案检索。 |
| **制作文书** | 使用 Word 模板生成所函、授权委托书等文书，支持模板占位符校验和批量生成。 |
| **处理日常事务** | 使用利息计算、发票、预付费用、录音转写、扫描件收件箱、法院通讯录等工具。 |
| **连接外部服务** | 按需配置大模型、MCP、邮箱、飞书等服务；部分功能依赖网络、第三方账号或额外组件。 |

> 功能以所使用的版本和实际配置为准。此仓库的源码可能比已发布应用更新；公开安装版可能不包含个人中心及其家庭财务同步功能。

## 开始使用

前往 **[官网安装指引](https://liu-zongjin.github.io/stella-downloads/download.html)**，选择 Mac 或 Windows，查看系统要求和源码安装步骤。官网提供可交给本机 AI 助手的安装指令。

- **Mac**：支持 macOS 12 及以上，Apple 芯片或 Intel。
- **Windows**：支持 Windows 10 1909 及以上或 Windows 11，Intel / AMD 64 位。Windows 版仍在测试，部分组件或功能可能不可用，升级前请备份资料。
- **源码安装**是试验方式，需要联网和额外磁盘空间；安装与更新说明请以官网及对应部署文档为准。

开发者可阅读 [macOS 源码部署](docs/MACOS_SOURCE_DEPLOYMENT.md)和 [Windows 源码部署](docs/WINDOWS_SOURCE_DEPLOYMENT.md)。如需浏览器方式运行本地服务，可参考下方开发说明。

## 数据与联网

案件、当事人、知识及附件等业务数据主要保存在本机数据库和文件中。AI、邮件、法律数据源、法院系统、云同步等功能需要连接相应服务，使用时可能向所选服务发送完成操作所需的数据；请根据服务条款和案件保密要求配置与使用。

应用和官网设有可关闭的匿名使用统计；具体行为可能因安装版本不同而有所差异。请定期备份本地数据库与附件，提交公开反馈时不要包含真实案件、个人信息、密钥或私人截图。

## 开发

Stella 的 macOS 桌面端采用 AppKit 与 WKWebView，业务服务由 FastAPI 和 SQLite 支撑；Windows 客户端使用相同的业务服务与前端。更多架构信息见 [系统地图](docs/architecture/SYSTEM_MAP.md)。

本地启动服务的基本方式：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-private.txt
npm ci
python3 start.py
```

默认访问 `http://localhost:8000`，可通过 `PORT` 环境变量调整端口。完整依赖、原生客户端构建及平台差异请参阅对应的源码部署文档。

| 目录 | 用途 |
| --- | --- |
| `frontend/` | 工作空间界面与共享组件 |
| `backend/` | 业务 API、数据库、集成与后台任务 |
| `native-shell/` | macOS 原生外壳 |
| `windows-installer/` | Windows 客户端与安装组件 |
| `tests/`、`scripts/` | 测试和维护工具 |
| `docs/` | 部署、架构与设计文档 |

提交改动前请阅读 [开发约定](AGENTS.md) 和 [贡献指南](CONTRIBUTING.md)。仓库提供 `python3 scripts/apex_guard.py preflight`、`fast` 和 `extended` 检查，按变更范围使用。

## 反馈与安全

使用问题和改进建议可通过 [GitHub Issues](https://github.com/liu-zongjin/apex-legal-os/issues)反馈。安全问题请遵循 [安全报告方式](SECURITY.md)，不要在公开 Issue 中披露敏感信息。

## 许可

Copyright © 2026 LIU Zongjin（刘宗锦律师）。本项目原创源码采用 [GNU Affero General Public License v3.0 only](LICENSE)，允许使用、修改和商业使用，并须遵守相应的源码提供与许可义务。

第三方代码、素材、依赖、字体、图标和商标保留各自权利；其中 `backend/case_archive.py` 所注明的 FachuanHybridSystem 改编材料适用 Elastic License 2.0。具体范围见 [NOTICE](NOTICE.md) 和 [第三方权利声明](THIRD_PARTY_NOTICES.md)。历史应用下载以随包许可为准；源码许可不改变已发布安装包的许可。
