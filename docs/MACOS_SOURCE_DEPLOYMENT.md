# macOS 源码部署（试验版）

本流程供能操作本机的 AI Agent 和有经验的用户使用。它从同一份源码构建 AppKit 客户端，并将用户资料保存在独立目录；不是正式签名、公证的安装包。请先用空白资料验证，不要声称尚未验证的功能已经可用。

## 给 AI Agent 的任务

> 请在这台 Mac 上，从 https://github.com/liu-zongjin/apex-legal-os 安装 Stella 源码版。先读取仓库的 `docs/MACOS_SOURCE_DEPLOYMENT.md`，检查本机环境，按说明安装依赖、编译并验证原生客户端能够打开和正常退出。保留已有 Stella 安装和所有用户资料，不要覆盖、重置或删除已有源码、数据库、附件、浏览器资料或设置，也不要关闭系统安全保护。需要安装系统软件、权限或遇到错误时请说明原因；未验证成功时不要说已经安装完成。

## 环境与首次安装

- Apple 芯片或 Intel Mac，macOS 12 或更新版本；需要 Git、适合本机架构的 Python 3.12、Apple 命令行开发工具、网络及充足的磁盘空间。首次安装 Python、开发工具或浏览器组件可能需要用户按系统提示授权。缺少组件时由 Agent 使用官方来源检查和安装，不更改系统安全设置。
- 克隆官方仓库的 `main` 到用户有写入权限的**新目录**，例如 `~/StellaSourceCode`。如果目录或目标应用已经存在，先检查并保留，不要强行覆盖。不要对现有仓库执行 `reset --hard`、`clean` 或覆盖未提交修改。
- Git 如出现 `HTTP2 framing` 等 HTTP/2 连接错误，可在保持现有代理设置的情况下，仅对该次命令加 `-c http.version=HTTP/1.1`，例如 `git -c http.version=HTTP/1.1 ls-remote https://github.com/liu-zongjin/apex-legal-os.git refs/heads/main`，克隆时同样在 `clone` 前加该参数。不要为尝试直连而清空 `HTTPS_PROXY` 或其他代理；代理、TLS 证书或网络问题仍需单独排查。
- 下列步骤在源码根目录执行，Python 依赖只安装到该目录由本流程创建的 `.venv`；已有但来源不明或不完整的环境会保留并停止安装。Playwright 浏览器使用当前用户的共享缓存。

```sh
bash scripts/macos/source-install.sh check
bash scripts/macos/source-install.sh install
bash scripts/macos/source-install.sh diagnose
bash scripts/macos/source-install.sh client
```

默认情况下客户端位于 `~/Applications/Stella Source.app`；使用 `STELLA_SOURCE_APP_DIR` 可放在其他位置，更新时必须找到用户实际使用的入口。客户端与已有 Stella 应用使用不同的身份和目录。首次启动创建 `~/Library/Application Support/StellaSource`；它不会导入其他版本的资料。源码客户端使用本机端口 18866，端口被占用时请先确认占用者，不要结束不明进程。关闭窗口可能保留菜单栏；使用应用菜单“退出 Stella”并等待后台保存结束。启动失败时检查该数据目录中的 `server.log`，分享错误前去除账号、路径和案件信息。

如果 pip 下载缓慢，可由用户按信任情况选择镜像，只对本次安装设置，例如 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash scripts/macos/source-install.sh install`；这不会改变全局配置。安装中断后可重新运行 `install`，脚本仅复用带有自身管理标记且完整的 `.venv`，不会接管来源不明的环境。

安装时 Playwright 会注册并检查共享浏览器缓存；如果安装或清理锁文件失败，脚本只有在当前 Playwright 对应的 Chromium 完整版可执行文件能运行且无头模式通过启动检查时才继续，否则仍报告失败；该检查不等同于验证有头浏览器和法院登录。`diagnose` 只检查 Python 依赖，并不能单独证明浏览器可用。不要直接删除共享缓存或 `__dirlock`：先确认没有其他 Playwright 安装在运行、检查权限；如仍失败，保留报错并由用户或管理员按本机策略处理。更换缓存目录会使该环境使用独立缓存，后续启动也必须使用同一环境变量。

验证时打开客户端，确认窗口和首页显示，检查案件管理、自动化立案及法院服务入口；退出并确认后台结束，然后重新打开确认资料保留。真实法院登录及外部 AI、邮件服务依赖用户自己的账号和网络，未实际操作时应明确说明。

## 源码更新

应用菜单“检查更新…”比较当前源码与 GitHub `main`；发现更新后可复制指令交给 Agent。更新需要联网并可能重新安装依赖、编译，不会因为代码合并自动修改用户电脑。不要将官网安装包安装到源码应用上。

Agent 执行更新时：

1. **定位实际入口，检查修改。** 先将最新 `main` 克隆到一个独立新目录，作为后续候选源码（保留现有源码；遇到 HTTP/2 错误见上方网络指引）。本检查工具可能尚不存在于旧版中，因此进入这个新目录后运行 `python3 scripts/macos/source-update-inspect.py`，查看 Spotlight、Dock 中发现的源码客户端及 18866 端口监听者。索引可能不完整，也请检查正在使用的窗口和 Dock；多个入口可能指向不同源码，不要仅凭同一个 bundle ID 判定。确认用户实际使用的应用后，运行 `python3 scripts/macos/source-update-inspect.py --app "实际应用路径"`；它读取该应用的 `CFBundleIdentifier`、`StellaSourceRoot`、Git 版本和未提交文件，并显示监听进程的 PID、父 PID、启动时间和命令行（包括后端的 `--runtime`）。与应用路径和源码根目录一起核对，不能仅凭端口判断进程归属。查询结果可能包含私人路径，分享前应脱敏。
2. 如果源码有已暂存、未暂存或未跟踪修改，向用户列出清单并说明克隆新版不会带入这些修改，取得用户对处理方式的确认后再切换；始终保留旧源码。可执行 `python3 scripts/macos/source-update-inspect.py --app "实际应用路径" --patch-dir "一个尚不存在的私有备份目录"`，分别导出已暂存、未暂存和相对旧提交的已跟踪文件补丁（支持二进制变更）及状态清单，保留暂存状态中的中间版本。补丁可能包含敏感内容，应保存在私有位置；**未跟踪和被忽略文件不在补丁中**，要从保留的旧源码或单独备份找回。不要自动套用补丁，也不要清理旧仓库。
3. 用应用菜单“退出 Stella”或 Cmd+Q 正常退出并等待保存、后台进程结束；**不要使用 `kill -TERM` 或强制退出应用作为正常验证手段**，这可能绕过后台关闭流程。再次检查 18866 和进程归属；如果仍有监听者或稍后重新出现，检查其命令行、`--runtime`、父进程和启动时间，先识别是否属于本次实例及是否有其他启动器；不要结束不明进程。确认是残留的源码后端且没有正在保存的工作时，优先通过原应用正常退出；仍无法处理时保留日志，征得用户对该特定进程和风险的确认后再人工处理，不要批量杀进程。
4. 确认足够磁盘空间：完整数据备份至少需要数据目录当前占用量，启动前数据库备份还需要约一个数据库的空间，新源码、`.venv`、浏览器下载和构建临时文件也需额外空间；预留余量，不能仅按数据库大小估算。`du -sh "$HOME/Library/Application Support/StellaSource"`、`df -h "$HOME"` 可帮助估算；复制到其他磁盘时也要检查目标磁盘。耗时取决于文件数量、磁盘和网络，不保证固定时长。
5. 使用第 1 步克隆的独立新目录，记录新旧 Git 提交号；在新目录执行 `check`、`install` 和 `diagnose`。可用 `git -C "新源码目录" log --oneline --max-count=20` 和 `CHANGELOG.md` 向用户概述变更；若新仓库包含旧提交，可用 `git -C "新源码目录" log --oneline 旧提交号..HEAD` 查看精确范围。运行 `STELLA_SOURCE_APP_DIR="新目录/dist/Stella Source.app" bash scripts/macos/source-install.sh client` 构建候选客户端，不覆盖现有应用。
6. 先在**全新临时空白数据目录**验证候选客户端的启动、首页和退出。自动化可直接执行候选应用的 `Contents/MacOS/Stella`，仅对该进程设置 `STELLA_SOURCE_RUNTIME` 为新临时目录、`STELLA_SOURCE_TEST_AUTO_QUIT=120`；启动完成后定时走应用的正常退出流程，无需操作 System Events。定时器从应用完成启动时起算，10–120 秒有效；验证应检查进程退出和 18866 释放，而不是仅等待计时。先确认端口空闲，不要将该变量用于用户日常运行的客户端，或将测试 runtime 指向真实资料。示例：

   ```sh
   test_runtime="$(mktemp -d "${TMPDIR:-/tmp}/stella-source-check.XXXXXXXX")"
   STELLA_SOURCE_RUNTIME="$test_runtime" STELLA_SOURCE_TEST_AUTO_QUIT=120 "候选应用路径/Contents/MacOS/Stella"
   lsof -nP -iTCP:18866 -sTCP:LISTEN
   ```

   期间另行验证首页及入口；若端口仍被占用，按第 3 步检查。测试结束后保留或清理由本次测试新建的空白目录，不触碰用户数据。
7. 将**第 1 步确认的实际应用**完整备份到用户可写的新路径，记录并报告该路径；确认备份成功后才把候选应用切换到这个实际入口。如果 Dock 指向其他路径，须同步确认入口，不要悄悄在默认路径新建另一个应用。遇到同名文件或来源不明时停止，不覆盖。首次启动新版前备份整个 `~/Library/Application Support/StellaSource`（如该应用使用了自定义 `STELLA_SOURCE_RUNTIME`，以实际目录为准），同时保留旧源码和旧 App。启动器在源码版本改变或无法识别时还会单独备份 SQLite 数据库，但它不包含附件、设置等全部资料。
8. 打开新版，检查原有案件和设置、退出及再次启动。如果切换或验证失败，保留日志、旧源码和备份，将原入口恢复；不要自动还原或覆盖数据库。数据库迁移后回退可能需要兼容的数据库备份，由 Agent 说明并征得用户具体确认。完整数据备份、旧 App 和旧源码应至少保留到用户确认新版和回退方案可靠；删除前由用户决定，切勿自动删除唯一可用备份。

### 数据库备份失败

`server.log` 中的 `sqlite3.OperationalError: disk I/O error` 表示 SQLite 无法完成读写，可能与空间、权限、磁盘或并发等多种因素有关，不能仅凭该信息断定 WAL 是原因，也不能认定原库损坏或完好。启动前备份失败会阻止本次后端启动，不会将新版本写入 `source-ready-revision`；后续重试仍会备份。先保留原数据库及其 `-wal`、`-shm` 文件、日志和整个数据目录，确认没有其他进程占用该资料，再检查磁盘空间、备份目录权限和系统错误；不要删除原库的 WAL、journal 或未经确认的文件。若问题持续，停止更新并请用户排查，不要通过跳过备份来强行启动。

新版将未完成的备份写为 `.db.partial` 并尽力清除本次残留；旧版可能留下 `before-source-start-*.db-journal` 或不完整的 `.db`。不能仅凭扩展名断定备份有效；保留可疑文件，检查无写入进程后，可在**副本**上使用 SQLite `PRAGMA quick_check` 检查已完成的数据库备份，并核对所需数据。检查通过也不替代整个数据目录的备份；清理可疑残留前先确认路径、归属和保留策略。

这是源码更新：合并到 GitHub `main` 后，用户执行上述流程即可获取对应源码，无需重新生成安装包；尚未合并的分支或旧源码中的本地修改不会自动进入新版。
