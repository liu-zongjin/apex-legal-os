# Windows 轻量引导安装器与发布验收

## 范围与状态

支持范围为 Windows 10 1809（内部版本 17763）及更新版本和 Windows 11 x64（Intel/AMD），覆盖家庭版、专业版、企业版，不按产品名称限定版本，一套业务源码和独立 Tauri Windows 壳。
安装器本身含小型冻结的安装工作进程，通过签名清单下载必要功能组件；WebView2
由 NSIS 自动检测/部署。Mac 原生壳与现有业务数据保持原位置。

Windows 排除 iCloud 通讯录、iCloud 日历、生物识别、Finder 标签、录音/音频导入、
夸克和飞书。司法短信改为粘贴/文本文件/截图预览、人工核对后导入，复用原有分析和
案件匹配，不因导入而自动生成业务事项。新增接口保留现有 Mac 扫描接口。

本次是开发实现，不是公开发行。CI 的 Windows Server 2022 构建机可验证编译、
安装内核、DPAPI 和冻结服务启动，但不能替代真实 Windows 10/11 桌面安装、通知和全部
外部业务验收。开发 CI 继续使用一次性开发公钥和空下载地址。独立的 production 候选流程
使用固定公开信任根，组装浏览器、OCR、文档转换器和业务服务，并在 CI 中实际试装、
验证组件复用及资料保留；它只保存私有候选产物，不自动公开发布。签名与公开托管
仍须依照用户明确授权及项目发布政策执行，不把 CI 当作实体设备全部业务验收。

## 目录与信任边界

- `windows-installer/`：Tauri 原生窗口和安装界面，NSIS 当前用户安装，无管理员要求。
- `scripts/windows/bootstrap_engine.py`：冻结的小型下载/安装工作进程，只依赖 requests、cryptography 和标准库；不包含案件数据库或业务模块。
- `scripts/windows/server_entry.py`：共享 FastAPI 的 Windows 启动入口，空用户目录、迁移前备份和合作式退出。
- `scripts/windows/build_payload.py`：复用共享 Git 暂存与脱敏流程生成 Windows 后端组件；不会复制开发者运行数据。
- `scripts/windows/make_catalog.py`：组件 ZIP、完整内容索引和 Ed25519 签名，不执行上传或发布。
- `backend/platform_capabilities.py`、`platform_files.py`、`windows_secrets.py`：能力、系统文件动作与用户级 DPAPI 存储。

NSIS 安装应用壳至当前用户的程序目录；组件缓存、版本和业务资料位于
`%LOCALAPPDATA%\Stella`。`userdata` 不参与组件替换；卸载应用壳不自动删除业务资料。

组件按 ZIP SHA-256 放入不可变的版本目录；每个文件还与签名清单核对。清单携带
目标架构、构建号、有效期、下载大小、展开大小及固定入口所需文件。下载只允许
编译配置授权的 HTTPS 主机，重定向同样验证。拒绝路径穿越、Windows 保留文件名、
重复大小写文件、符号链接、超额解压和目录外写入。不会执行服务器下发的自由命令行。

激活前还会在临时目录实际检查后端依赖、OCR 中英文语言包、浏览器页面渲染和
文档转 PDF；自检失败不切换版本。全部组件成功后原子更新 `active.json`，保留 `previous.json`。安装和运行持有同一
生命周期锁，禁止在后台仍运行时替换组件。保留旧组件不等于支持任意数据库降级；
模式迁移失败须基于迁移前备份恢复，不能仅回退一个 exe。

## 消息与更新

共享首页继续读取现有 `/v1/messages` 消息源，无安装标识或统计授权依赖。Windows
在原生桥就绪后可额外显示系统通知；关闭通知不影响应用内消息。主窗口运行时
启动/回到前台/网络恢复及定期检查更新；退出和关机不运行通知服务。

组件更新提示后要求用户先保存工作，合作式关闭后端，再返回安装界面更新。更新
失败保留现有版本。当前通道配置为空时明确显示无法检查，不伪装成“已是最新”。
本版清单负责业务组件更新；桌面壳/安装器自身升级的完整签名发行流程仍须结合
正式 Windows 发行版本验收，不能把组件更新测试当作壳自身更新已验证。

## 构建与检查

在 Windows 的独立虚拟环境安装 `scripts/windows/requirements-bootstrap.txt` 与
`requirements-runtime.txt`。后者对兼容敏感的共享库固定版本，不更改 Mac 运行环境。
安装器前端使用 `windows-installer/package-lock.json` 与 `npm ci`。

1. `python -m unittest tests.test_windows_bootstrap tests.test_manual_judicial_import tests.test_platform_files -v`
2. 通过 `make_catalog.py` 从已审计的 `server`、`browser`、`ocr`、`converter` 组件生成清单；可选 `node`。生产使用稳定私钥，开发使用明确的一次性密钥。私钥不进入组件或仓库。
3. 将清单公钥、固定下载地址与允许主机写入被忽略的 `windows-installer/bootstrap-config.json`。在线地址与已签名离线目录使用相同信任根。
4. 使用 PyInstaller 冻结 `bootstrap_engine.py`，将上述配置作为数据文件嵌入，输出 `windows-installer/src-tauri/resources/bootstrap-engine.exe`。
5. 在 `windows-installer` 执行 `npm run build`，得到 NSIS setup exe。构建管线检查其小于 500,000,000 字节。
6. `python scripts/windows/build_payload.py --output <全新暂存路径>` 构建后端；`smoke_backend.py <StellaServer.exe>` 只在匿名临时目录运行。开发 CI 不打包真实本机资料。

浏览器组件固定入口 `chrome.exe`；OCR 为 `tesseract.exe`，语言数据放 `tessdata/`；
转换器为 `program/soffice.exe`，命令行操作优先使用同目录 `soffice.com`；服务为 `StellaServer.exe`。它们必须包含经过实际验证的
完整依赖和第三方声明。当前 CI 先生成壳和服务验证，不会自动从未知来源拼装并
公开分发这些第三方组件。不能凭一个存在的文件名判断组件可用。

`tests/windows_installer_ui.py` 可用模拟原生桥检查界面浅色/深色、计划、进度与按钮；
其截图数字为测试数据，不是实际安装包大小或 Windows 实测证明。

## 尚须完成的发行验收

- 真实 Windows 10（优先 22H2）和 Windows 11 干净机器完整安装，包括 WebView2 缺失、中文路径、断点重试及组件实际启动。
- 全量第三方组件的来源、版本、许可、实际体积和功能回归；本地 MCP/CLI、扫描设备与备份调度等完整流程。
- Windows 文件剪贴板、特殊格式预览、法院登录与验证码接管、多账号、邮件、文档分页和中文 OCR 对比。
- 系统消息与更新通道实际可达性、通知点击、权限拒绝、休眠恢复，以及壳自身升级和业务数据保留。
- 正式签名、稳定更新密钥与托管；只在用户明确批准测试后发行时才上传公开安装器、组件和更新清单。

这些项目未完成前，本版只作为可复核的开发里程碑，不对外声称“所有功能开箱即用”。

## Windows 10 兼容依据

系统检测使用内部版本号和工作站产品类型，不将 Windows 10 一律排除；拒绝更早系统、Server、32 位及 ARM 架构。WebView2 仍由 NSIS 检测并补装。最低版本结合随包 OCR 的 ONNX Runtime Windows 10 1809+ 边界确定；21H2、22H2 和 Windows 11 共用一条安装路径。

参考：[Tauri Windows 安装器](https://v2.tauri.app/distribute/windows-installer/)、[ONNX Runtime Windows 支持](https://onnxruntime.ai/docs/get-started/with-windows.html)。模拟版本检测和 Windows Server CI 编译通过不等于真实 Windows 10 桌面验收。


## 稳定签名通道与完整候选构建

- `scripts/windows/production-trust.json` 仅包含稳定 Ed25519 公钥、固定 Pages 清单地址与 HTTPS 主机白名单。私钥在发布者本机受限目录 `~/.config/stella-windows/release-ed25519.key`，不得提交或传入 CI。
- `.github/workflows/windows-production.yml` 只构建私有候选；`build_components.py` 使用固定 Playwright Chromium、conda-forge Tesseract 及官方 LibreOffice MSI，记录来源、SHA-256 和许可。第三方程序不在开发者本机全局安装。
- NSIS 在临时中文目录实际解包安装，检查安装后的主程序、工作进程、内嵌公开配置及中文资料路径探测。Server CI 仍不能替代实体 Windows 10/11 的桌面安装验收。
- 冻结服务逐页浏览器检查并验证法答网导出、匿名资料升级备份与保留。完整组件必须实际完成浏览器渲染、OCR 识别及 PDF 转换；Windows Visual C++ 运行库随组件提供并检查 PE 引用，防止依赖构建机的全局环境。
- 子程序避免在不可变组件目录写 Python 字节码，浏览器日志输出重定向；自检后再次逐文件核验，任何内容变化都不能激活新版本。
- 真正的组件升级试装会改变服务组件内容，确认浏览器/OCR/转换器复用、只下载服务组件，并保留匿名用户附件。Windows 是组件级增量，改变的服务组件仍下载完整组件 ZIP；Mac Sparkle 使用对应旧版本的二进制增量包。
- `retain_production.py` 只把干净候选拆分保存到私有临时 CI 分支。发布者取回后复核每个 ZIP 和文件索引，使用本机稳定私钥签名，再先上传不可变组件与安装器，最后发布 Pages 的 `windows/catalog.json`。
- 发布新清单时，未变化的依赖应保留原组件描述、SHA-256 与不可变下载地址，不要为了版本号重新打包全部依赖。清单有有效期，续期也必须使用本机稳定私钥重新签名；不得更换成一次性信任根。

早期开发引导器并无可用正式通道，不能承诺远程补装更新器。初次正式体验发行需重新运行公开引导器；独立资料目录始终保留，组件替换不会删除它。原生壳自身的后续升级与业务组件更新是不同流程，不能声称壳自更新已完成全部验收。
