# Windows 源码部署（试验版）

浏览器模式是默认安装方式，适用于 Windows 10 1909 及以上和 Windows 11 的 Intel / AMD 64 位电脑。Stella 使用项目内的 Python 运行环境，在本机启动服务，再用默认浏览器打开工作台。此模式只准备 Git、64 位 Python 3.12 和项目依赖，无需下载 Rust、VS C++ 构建工具、WebView2 或法院自动化 Chromium 才能进入首页。

## 给 AI Agent 的任务

> 请从 https://github.com/liu-zongjin/apex-legal-os 的 main 分支在这台 Windows 电脑上安装 Stella 源码版。阅读仓库的 `docs/WINDOWS_SOURCE_DEPLOYMENT.md`，默认使用浏览器模式。保留现有安装、快捷方式、数据库、附件和配置。验证桌面快捷方式能启动本机服务并打开工作台，退出后端口释放。失败时报告实际错误和最后完成的步骤。

## 浏览器模式

1. 检查系统架构、Git 和现有 Stella 安装。首次安装用 `git clone --depth 1 --single-branch --branch main https://github.com/liu-zongjin/apex-legal-os.git` 克隆到用户可写的长期目录。已有浏览器模式快捷方式时，先核对它指向的源码目录，使用下文的更新步骤。如电脑尚无 Git，可通过官方 Git for Windows 安装，或从官方源码 ZIP 临时执行文档所列的预检；完成后用 Git 克隆正式安装目录。
2. 在已核实的源码根目录打开 PowerShell，执行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action quick
   ```

   安装会检查本机依赖，仅在需要时通过 winget 补装 Git 和 Python，准备项目内 `.venv`，创建桌面快捷方式 **Stella Source (Browser)** 和 **退出 Stella**，并启动 Stella。已有依赖和指向同一源码目录的快捷方式可复用。若 winget 不可用，通过官方渠道补齐 Python 3.12 x64 和 Git 后重试。执行策略仅用于这一次 PowerShell 进程。
3. 确认浏览器实际显示工作台首页，地址是 `http://127.0.0.1:18865/`。日常双击 Stella 快捷方式，服务在后台启动，准备就绪后打开浏览器；首次启动和数据备份仍需时间。只关闭浏览器标签页会让本地服务继续运行；保存工作后双击桌面 **退出 Stella** 可正常关闭服务。请验证退出后端口释放、双击重开可以读取已有资料。启动失败时查看 `%LOCALAPPDATA%\StellaSource\browser-server.log`，分享前去除个人信息。端口占用时先核实占用者。

已有源码和 Python 环境时，也可用 `-Action browser` 直接启动并自动打开页面。没有 Git 时，先从官方来源获取源码 ZIP，在临时目录运行 `-Action provision -BrowserMode`，安装后重新打开终端再克隆。此方式同样会补装缺失的 Python。

案件、附件和设置使用 `%LOCALAPPDATA%\StellaSource`，此前安装过 Tauri 源码版的用户可以继续读取这一目录中的资料。切换前先关闭正在运行的 Stella；两种方式共享同一资料锁。历史独立安装包的资料目录不自动导入。浏览器模式通过下面的 AI 指令检查和更新，Windows 系统通知与原生更新菜单由 Tauri 方式提供。

### 首次用到法院服务浏览器时

法院官网登录、需浏览器的文书下载等功能，可在使用前请 AI 助手从已安装的源码目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action install-browser
```

成功后重试该功能。Chromium 使用 Playwright 的本机共享缓存；相同版本可在不同源码目录复用。下载失败只需重试这一项。AI、邮件、OCR 和文档转换按实际功能另行配置。

### 浏览器模式的源码更新

请让 AI 助手读取桌面 **Stella Source (Browser)** 快捷方式指向的源码目录，检查现有资料并停止正在运行的 Stella，备份整个 `%LOCALAPPDATA%\StellaSource`。在当前源码目录中核对官方 main 的 40 位提交号，确认需要更新后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-update.ps1 -CurrentRoot (Get-Location).Path -ExpectedRevision <官方提交号> -BrowserMode
```

将 `<官方提交号>` 替换成实际值。更新会在独立目录下载和验证候选版本，用临时空白资料检查首页、启动与退出，通过后才切换浏览器快捷方式。重新打开并确认原有案件可读。旧源码与快捷方式备份可用于排查；如已发生数据库迁移，回退前须核对备份与数据库兼容性。

从仍显示黑色窗口的旧版首次更新后，如果桌面入口仍指向 `python.exe`，请在已核实的新源码目录执行 `-Action quick -NoLaunch`，升级同一安装的桌面入口并创建退出入口；不要覆盖指向其他安装的快捷方式。

## 原生桌面窗口（Tauri，可选）

以下流程供需要 Tauri 原生窗口、系统通知或原生更新菜单的用户使用。使用空白测试资料验证桌面集成、OCR、浏览器自动化和 Office 转换功能。

### 环境与准备

- Intel/AMD 64 位电脑；自动安装 VS 2022 C++ 工具需要受支持的 Windows 10 1909 或更新版本。1809 到 1903 的源码编译环境未验证。需要可用磁盘空间和访问 GitHub、Python 软件源的网络。
- 系统依赖可由下面的 `provision` 步骤检查并通过 Windows 包管理器安装：Git、64 位 Python 3.12、Rust、Microsoft C++ 构建工具和 WebView2 Runtime。安装器可能需要用户确认权限或重启；不要关闭系统安全保护。若 winget 不可用，Agent 应使用各软件的官方安装方式并在失败时说明原因。
- 使用 Git 克隆官方仓库到用户有写权限的独立目录。若尚无 Git，可先下载官方源码 ZIP，在临时目录运行 `provision` 安装 Git，然后用 Git 克隆正式目录；不要把 ZIP 临时目录当成正式安装。源码更新检查需要 Git 仓库。不要把源码放到已有安装或数据目录。
- 若目标目录已有仓库或 `.venv`，先检查其来源和状态；不要强制覆盖、重置、删除或自动更新它。运行前确认仓库版本和本说明对应。
- 本流程将新数据放在 `%LOCALAPPDATA%\StellaSource`，不会自动导入或替换已安装版本的数据。该目录已存在时视为现有资料，需保留；当源码版本变化、无法识别版本或存在本地修改时，启动前会将 SQLite 数据库备份至 `data\history_backups`；版本仅在服务成功启动后记录。已有备份不会自动删除。不要同时运行多个源码服务或手动覆盖数据库。

### 执行

在源码根目录打开 PowerShell，依次执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action check
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action provision
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action install
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action diagnose
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\source-install.ps1 -Action client
```

这里的执行策略只作用于单次 PowerShell 进程，不更改系统设置。安装只使用项目内 `.venv`，不会修改系统 Python 依赖。`client` 在本机编译外壳并建立“Stella Source”桌面快捷方式；双击后自动打开应用窗口和本地服务，关闭窗口时等待后台退出。首次启动创建空白数据库；AI、邮件等服务需要用户自行配置。源码模式使用固定端口 18865，运行前请关闭占用该端口的程序，包括已有 Stella 实例。可在「设置 → 系统与支持 → 基础使用统计」关闭匿名使用统计。

客户端编译成功后会清理该项目的 Cargo 中间产物，并保留快捷方式使用的程序。后续重新编译可能需要更长时间；不会清理共享的 Rust、Python 或浏览器缓存。

新建的项目 Python 环境在支持的 Windows 文件系统上启用透明压缩；不支持时自动按普通方式安装。已有环境不修改压缩设置。安装不再额外保存新的 pip 下载缓存，可能使重装时需要重新下载。Playwright 浏览器默认使用系统用户目录中的共享缓存，多个源码版本可复用；各版本仍保留独立 Python 环境，以免更新影响回退。压缩效果取决于文件系统和依赖内容，安装、更新时仍需预留临时空间。

### 验证与排错

1. 双击桌面快捷方式，确认 Stella 窗口能打开且首页正常显示；关闭后再次打开，确认数据保留。仅编译成功不等于客户端已验证可用。
2. 端口被占用时，先确认是否已有 Stella 正在运行；不要终止不明进程。源码客户端固定使用 18865 端口。
3. 找不到 Python：确认安装的是 64 位 3.12，重新打开 PowerShell 后执行 `check`。安装依赖失败：查看 pip 的实际错误，检查网络、代理、磁盘空间和权限，再重试 `install`。
4. 启动失败：点击「重试启动」。若仍失败，查看 `%LOCALAPPDATA%\StellaSource\source-client.log`，或执行 `diagnose` 检查依赖。向他人反馈前删除日志中的用户名、路径、密钥、案件或个人信息；不要发送数据库和附件。
5. `provision` 不配置开机启动。依赖包更新、Windows 包管理器不可用或网络变化可能导致安装失败；遇到问题应记录 Windows 版本、源码版本、Python 版本及去敏错误信息。

### 原生桌面窗口的源码更新

源码客户端的“检查更新”对照官方 GitHub `main`。用户保存工作并选择更新后，客户端关闭服务，更新窗口将新源码下载到独立目录，安装依赖、编译并在临时空白资料中检查启动和退出；检查通过后才切换桌面快捷方式。旧源码和旧快捷方式备份均保留。每次成功更新后，自动检查此前由此流程创建的更早版本：仅当独立 Python 环境与安装后记录完全一致时，才移除该环境；当前版本和紧邻的上一版本始终保留。含有新增、修改或链接的环境，源码存在修改或无法确认状态的版本，以及没有记录的旧环境均不会自动清理。更早的快捷方式备份仍存在，但其环境若已清理，需重新安装依赖后才能使用。首次打开新版前请备份整个 `StellaSource` 数据目录；启动器会额外备份数据库。源码更新需要 GitHub、Python 软件源和足够磁盘空间，速度取决于网络和本机编译能力。更新失败时不要删除旧版本或用户资料；如新版启动失败，保留日志和备份，由 Agent 协助诊断。
