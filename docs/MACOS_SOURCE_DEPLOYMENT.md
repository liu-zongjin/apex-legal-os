# macOS 源码部署（试验版）

本流程供能操作本机的 AI Agent 和有经验的用户使用。它从同一份源码构建 AppKit 客户端，并将用户资料保存在独立目录；不是正式签名、公证的安装包。请先用空白资料验证，不要声称尚未验证的功能已经可用。

## 给 AI Agent 的任务

> 请在这台 Mac 上，从 https://github.com/liu-zongjin/apex-legal-os 安装 Stella 源码版。先读取仓库的 `docs/MACOS_SOURCE_DEPLOYMENT.md`，检查本机环境，按说明安装依赖、编译并验证原生客户端能够打开和正常退出。保留已有 Stella 安装和所有用户资料，不要覆盖、重置或删除已有源码、数据库、附件、浏览器资料或设置，也不要关闭系统安全保护。需要安装系统软件、权限或遇到错误时请说明原因；未验证成功时不要说已经安装完成。

## 环境与首次安装

- Apple 芯片或 Intel Mac，macOS 12 或更新版本；需要 Git、适合本机架构的 Python 3.12、Apple 命令行开发工具、网络及充足的磁盘空间。首次安装 Python、开发工具或浏览器组件可能需要用户按系统提示授权。缺少组件时由 Agent 使用官方来源检查和安装，不更改系统安全设置。
- 克隆官方仓库的 `main` 到用户有写入权限的**新目录**，例如 `~/StellaSourceCode`。如果目录或目标应用已经存在，先检查并保留，不要强行覆盖。不要对现有仓库执行 `reset --hard`、`clean` 或覆盖未提交修改。
- 下列步骤在源码根目录执行，Python 依赖只安装到该目录由本流程创建的 `.venv`；已有但来源不明或不完整的环境会保留并停止安装。Playwright 浏览器使用当前用户的共享缓存。

```sh
bash scripts/macos/source-install.sh check
bash scripts/macos/source-install.sh install
bash scripts/macos/source-install.sh diagnose
bash scripts/macos/source-install.sh client
```

客户端位于 `~/Applications/Stella Source.app`，与已有 Stella 应用使用不同的身份和目录。首次启动创建 `~/Library/Application Support/StellaSource`；它不会导入其他版本的资料。源码客户端使用本机端口 18866，端口被占用时请先确认占用者，不要结束不明进程。关闭窗口可能保留菜单栏；使用应用菜单“退出 Stella”并等待后台保存结束。启动失败时检查该数据目录中的 `server.log`，分享错误前去除账号、路径和案件信息。

验证时打开客户端，确认窗口和首页显示，检查案件管理、自动化立案及法院服务入口；退出并确认后台结束，然后重新打开确认资料保留。真实法院登录及外部 AI、邮件服务依赖用户自己的账号和网络，未实际操作时应明确说明。

## 源码更新

应用菜单“检查更新…”比较当前源码与 GitHub `main`；发现更新后可复制指令交给 Agent。更新需要联网并可能重新安装依赖、编译，不会因为代码合并自动修改用户电脑。不要将官网安装包安装到源码应用上。

Agent 执行更新时：

1. 通过应用菜单退出源码客户端并确认本机 18866 端口已释放；读取现有应用 `Contents/Info.plist`，确认 `CFBundleIdentifier` 为 `com.stella.source.native`，并确认 `StellaSourceRoot` 指向当前源码。保留所有已有源码、应用与数据；不要原地覆盖或清理。
2. 将最新 `main` 克隆到新的独立目录，记录其 Git 提交号；在新目录执行 `check`、`install` 和 `diagnose`。运行 `STELLA_SOURCE_APP_DIR="新目录/dist/Stella Source.app" bash scripts/macos/source-install.sh client` 构建候选客户端，不覆盖现有应用。
3. 先在临时空白数据目录验证候选客户端的启动、首页和退出。可仅对该测试进程设置 `STELLA_SOURCE_RUNTIME` 为一个新的临时目录；不要把变量指向已有资料。确认进程完全退出且端口释放，再进行下一步。
4. 将原应用完整备份到用户可写的新路径，确保备份成功，再切换 `~/Applications/Stella Source.app` 为候选应用；遇到同名文件或来源不明时停止，不覆盖。首次启动新版前备份整个 `~/Library/Application Support/StellaSource`；启动器还会在源码版本改变或无法识别时备份 SQLite 数据库。
5. 打开新版，检查原有案件和设置、退出及再次启动。如果切换或验证失败，保留日志、旧源码和备份，将原入口恢复；不要自动还原或覆盖数据库。数据库迁移后回退可能需要兼容的数据库备份，由 Agent 说明并征得用户具体确认。

这是源码更新：合并到 GitHub `main` 后，用户执行上述流程即可获取对应源码，无需重新生成安装包；但不会自动获取尚未合并的分支或作者电脑上的未提交修改。
