# Windows 源码部署（试验版）

本流程面向能操作本机的 AI Agent 和有经验的用户。它编译现有 Tauri Windows 外壳并连接源码服务，属于试验版，不等同于正式 Windows 安装包。请先使用空白测试资料，不要用于生产案件。某些桌面集成、OCR、浏览器自动化、Office 转换和更新功能还需要单独验证或安装额外组件。

## 给 AI Agent 的任务

> 请在我当前使用的 Windows 电脑上，从 https://github.com/liu-zongjin/apex-legal-os 安装 Stella 源码版。先读取仓库的 `docs/WINDOWS_SOURCE_DEPLOYMENT.md`，按其中的检查、安装和验证步骤执行。请保留已有 Stella 安装与数据，不要删除、覆盖或重置任何用户资料，也不要关闭系统安全保护。如果需要我确认权限或安装软件，请说明原因；失败时根据实际错误诊断，不要声称安装成功。

## 环境与准备

- Windows 10 1809 或更新版本的 Intel/AMD 64 位电脑；需要可用磁盘空间和访问 GitHub、Python 软件源的网络。
- 安装 64 位 Python 3.12（官方来源 https://www.python.org/downloads/windows/）。安装器可能需要用户确认权限。不要为了绕过失败而关闭安全软件。
- 安装 Rust 工具链（https://rustup.rs/）、Microsoft C++ 构建工具及 WebView2 Runtime；需要网络、磁盘空间及可能的权限确认。安装后重新打开终端，确保 `cargo` 可用。Agent 应按照官方安装器提示操作，不应关闭系统保护。
- 使用 Git 克隆官方仓库，或从官方 GitHub 下载源码 ZIP 并解压到用户有写权限的独立目录。不要把源码解压到已有安装或数据目录。
- 若目标目录已有仓库或 `.venv`，先检查其来源和状态；不要强制覆盖、重置、删除或自动更新它。运行前确认仓库版本和本说明对应。
- 本流程将新数据放在 `%LOCALAPPDATA%\StellaSource`，不会自动导入或替换已安装版本的数据。该目录已存在时视为现有资料，需保留；数据库每次启动前进行 SQLite 备份至其 `data\history_backups` 文件夹。不要同时运行多个源码服务或手动覆盖数据库。

## 执行

在源码根目录打开 PowerShell，依次执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action check
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action install
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action diagnose
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action client
```

这里的执行策略只作用于单次 PowerShell 进程，不更改系统设置。安装只使用项目内 `.venv`，不会修改系统 Python 依赖。`client` 在本机编译外壳并建立“Stella 源码版”桌面快捷方式；双击后自动打开应用窗口和本地服务，关闭窗口时等待后台退出。首次启动创建空白数据库；AI、邮件等服务需要用户自行配置。源码模式使用固定端口 18865，运行前请关闭占用该端口的程序，包括已有 Stella 实例。源码版的安装器更新和匿名统计入口暂不可用。

## 验证与排错

1. 双击桌面快捷方式，确认 Stella 窗口能打开且首页正常显示；关闭后再次打开，确认数据保留。仅编译成功不等于客户端已验证可用。
2. 端口被占用时，先确认是否已有 Stella 正在运行；不要终止不明进程。源码客户端固定使用 18865 端口。
3. 找不到 Python：确认安装的是 64 位 3.12，重新打开 PowerShell 后执行 `check`。安装依赖失败：查看 pip 的实际错误，检查网络、代理、磁盘空间和权限，再重试 `install`。
4. 启动失败：执行 `diagnose` 并检查启动窗口的错误。向他人反馈前删除日志中的用户名、路径、密钥、案件或个人信息；不要发送数据库和附件。
5. 脚本不会自动安装 Git、Python、Rust、C++ 工具、WebView2、浏览器或 OCR 系统程序，也不配置开机启动。依赖包更新或网络变化可能导致安装失败；遇到问题应记录 Windows 版本、源码版本、Python 版本及去敏错误信息。

如需更新源码，先停止服务并备份整个 `StellaSource` 数据目录，然后在独立测试环境验证新版。不要让 Agent 强制重置或覆盖已有用户资料。
