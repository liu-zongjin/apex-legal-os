# Windows 源码部署（试验版）

本流程面向能操作本机的 AI Agent 和有经验的用户。它编译现有 Tauri Windows 外壳并连接源码服务，属于试验版，不等同于正式 Windows 安装包。请先使用空白测试资料，不要用于生产案件。某些桌面集成、OCR、浏览器自动化和 Office 转换功能还需要单独验证或安装额外组件。

## 给 AI Agent 的任务

> 请在我当前使用的 Windows 电脑上，从 https://github.com/liu-zongjin/apex-legal-os 安装 Stella 源码版。先读取仓库的 `docs/WINDOWS_SOURCE_DEPLOYMENT.md`，按其中的检查、安装和验证步骤执行，创建桌面快捷方式并验证客户端窗口能打开和正常关闭。请保留已有 Stella 安装与数据，不要删除、覆盖或重置任何用户资料，也不要关闭系统安全保护。如果需要我确认权限或安装软件，请说明原因；失败时根据实际错误诊断，不要声称安装成功。

## 环境与准备

- Intel/AMD 64 位电脑；自动安装 VS 2022 C++ 工具需要受支持的 Windows 10 1909 或更新版本。1809 到 1903 的源码编译环境未验证。需要可用磁盘空间和访问 GitHub、Python 软件源的网络。
- 系统依赖可由下面的 `provision` 步骤检查并通过 Windows 包管理器安装：Git、64 位 Python 3.12、Rust、Microsoft C++ 构建工具和 WebView2 Runtime。安装器可能需要用户确认权限或重启；不要关闭系统安全保护。若 winget 不可用，Agent 应使用各软件的官方安装方式并在失败时说明原因。
- 使用 Git 克隆官方仓库到用户有写权限的独立目录。若尚无 Git，可先下载官方源码 ZIP，在临时目录运行 `provision` 安装 Git，然后用 Git 克隆正式目录；不要把 ZIP 临时目录当成正式安装。源码更新检查需要 Git 仓库。不要把源码放到已有安装或数据目录。
- 若目标目录已有仓库或 `.venv`，先检查其来源和状态；不要强制覆盖、重置、删除或自动更新它。运行前确认仓库版本和本说明对应。
- 本流程将新数据放在 `%LOCALAPPDATA%\StellaSource`，不会自动导入或替换已安装版本的数据。该目录已存在时视为现有资料，需保留；当源码版本变化、无法识别版本或存在本地修改时，启动前会将 SQLite 数据库备份至 `data\history_backups`；版本仅在服务成功启动后记录。已有备份不会自动删除。不要同时运行多个源码服务或手动覆盖数据库。

## 执行

在源码根目录打开 PowerShell，依次执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action check
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action provision
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action install
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action diagnose
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action client
```

这里的执行策略只作用于单次 PowerShell 进程，不更改系统设置。安装只使用项目内 `.venv`，不会修改系统 Python 依赖。`client` 在本机编译外壳并建立“Stella Source”桌面快捷方式；双击后自动打开应用窗口和本地服务，关闭窗口时等待后台退出。首次启动创建空白数据库；AI、邮件等服务需要用户自行配置。源码模式使用固定端口 18865，运行前请关闭占用该端口的程序，包括已有 Stella 实例。源码版匿名统计入口暂不可用。

客户端编译成功后会清理该项目的 Cargo 中间产物，并保留快捷方式使用的程序。后续重新编译可能需要更长时间；不会清理共享的 Rust、Python 或浏览器缓存。

新建的项目 Python 环境在支持的 Windows 文件系统上启用透明压缩；不支持时自动按普通方式安装。已有环境不修改压缩设置。安装不再额外保存新的 pip 下载缓存，可能使重装时需要重新下载。Playwright 浏览器默认使用系统用户目录中的共享缓存，多个源码版本可复用；各版本仍保留独立 Python 环境，以免更新影响回退。压缩效果取决于文件系统和依赖内容，安装、更新时仍需预留临时空间。

## 验证与排错

1. 双击桌面快捷方式，确认 Stella 窗口能打开且首页正常显示；关闭后再次打开，确认数据保留。仅编译成功不等于客户端已验证可用。
2. 端口被占用时，先确认是否已有 Stella 正在运行；不要终止不明进程。源码客户端固定使用 18865 端口。
3. 找不到 Python：确认安装的是 64 位 3.12，重新打开 PowerShell 后执行 `check`。安装依赖失败：查看 pip 的实际错误，检查网络、代理、磁盘空间和权限，再重试 `install`。
4. 启动失败：执行 `diagnose` 并检查启动窗口的错误。向他人反馈前删除日志中的用户名、路径、密钥、案件或个人信息；不要发送数据库和附件。
5. `provision` 不配置开机启动。依赖包更新、Windows 包管理器不可用或网络变化可能导致安装失败；遇到问题应记录 Windows 版本、源码版本、Python 版本及去敏错误信息。

## 源码更新

源码客户端的“检查更新”对照官方 GitHub `main`。用户保存工作并选择更新后，客户端关闭服务，更新窗口将新源码下载到独立目录，安装依赖、编译并在临时空白资料中检查启动和退出；检查通过后才切换桌面快捷方式。旧源码和旧快捷方式备份均保留。首次打开新版前请备份整个 `StellaSource` 数据目录；启动器会额外备份数据库。源码更新需要 GitHub、Python 软件源和足够磁盘空间，速度取决于网络和本机编译能力。更新失败时不要删除旧版本或用户资料；如新版启动失败，保留日志和备份，由 Agent 协助诊断。
