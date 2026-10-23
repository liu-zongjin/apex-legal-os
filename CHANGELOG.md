## 2026-10-23 Windows 本地文件选择（测试修正，未发布）

- 自动化立案、案件详情、办案工作台等共用的 Windows 文件／文件夹选择器改为直接调用系统窗口，关联当前前台窗口，不再通过 PowerShell 弹窗。保留中文路径、取消选择与既有绑定接口。
- 私下测试构建同时包含启动交接修正和新业务组件；实际显示、选择和绑定仍待用户设备复测。

## 2026-10-23 Windows 启动交接与诊断（本地修正，未发布）

- 后台确认就绪后先完成原生启动调用，再由安装页面打开固定的本机工作空间地址；避免原生调用尚未结束就替换安装页面。
- 启动等待显示实际耗时，启动退出／超时在等待安全关闭之前提示原因和日志位置；本机日志补充初始化阶段。保留启动完整校验及合作式关闭。
- 浏览器模拟覆盖正式页面跳转与失败提示；尚须在报告故障的 Windows 设备上复测，不代表已修复已安装版本或完成公开发行。

## 2026-10-23 本地数据与源码分离（未发布）

- 以今日清理后的 GitHub 历史为基准迁移任务执行功能。律所、银行账户与用章审批人从本地数据库读取，取消示例人员和客户的自动初始化；保留既有本地业务数据。

## 2026-10-23 — 材料分析任务（本地迭代，未发布）

- AI 增强增加“执行任务”入口，办案工作台新增“材料分析任务”：清点所选材料、生成有来源的时间线、分析关键事项／争点／矛盾与补证建议，并导出待复核草稿。
- 任务与材料版本持久保存，支持暂停、停止、继续及刷新后找回；重复请求和重启恢复复用同一子任务，已完成批次不重复调用模型。
- 固定所选模型及服务配置，请求上限计入重试；阻止未经授权的备用模型调用。材料变化时阻止继续和下载旧成果。
- 支持关联本案已有研究项目；独立未关联项目、外部法律研究、业务写回和对外提交不在本轮开放。沿用现有依赖，无 LangGraph 或新模型运行环境。

## 2026-10-23 — Windows 1.1.6 引导安装器

- Windows：首次启动征求匿名统计授权，同意后立即上报一次，此后每六小时最多一次；重启、断网和重新授权不会重置间隔，可随时在工具栏关闭。

- 发布真实下载及校验进度、下载速度和阶段剩余时间，加入低速重连与安全备用源机制。
- 合并重复校验读取，保留安装后和启动前完整性检查；使用最新共享业务源码，保留升级资料。

## 2026-10-22 — 本地与公开版更新入口统一（本地修正，未发布）

- 本地 Stella 菜单增加“检查更新…”，与公开版共用 Sparkle、更新源和验证公钥。
- 本地源码工作区展示官网可用版本；阻止公开安装包直接替换源码连接、应用身份及数据位置。公开安装版继续使用确认后的完整包／增量更新。
- 本地原生构建成功后才替换应用，保留旧应用作为恢复点；本次不发布任何安装包。

## 2026-10-22 — 知识库法条定位

- 法条跳转按中英文数字归一化后的准确条号定位，支持条号与正文被加粗等格式分开，避免排版后的字符偏移跳到其他条文。
- 条文索引优先识别段落自身条号，修正继承标题干扰与历史错误段落位置；普通原文引用支持跨格式匹配。

## 2026-10-22 — 法院附件归档可靠性

- 修复 macOS 归档文件夹的可选标签依赖加载失败时，已关联案件的法院附件错误退回默认下载目录的问题；单个下载与全部下载仍归档到绑定的案件文件夹。

## 2026-10-22 — Windows 安装器性能与进度（本地改进，未发布）

- 合并下载、离线复制和解压中的重复哈希读取，减少安装中间的重复扫描；保留自检后及每次启动前的完整校验。
- 下载增加持续低速重连、断点续传和签名保护的备用源机制，现有正式来源保持不变。
- 总下载量、当前组件下载、解压校验、文件检查与启动分开显示；增加平均速度和剩余下载时间，取消循环动画及过期下载提示。

## 2026-10-21 — 案件编辑器稳定性审查

- 修正 A4 分页过程中滚动偏移导致的过期坐标计算，增加不收敛退出和耗时保护；必要时无损切换连续显示。
- 修复旧窗口的异步定位干扰新窗口，以及源文模式切换丢失滚动进度。
- 案件记录的 Excel 导出转换富文本标签为可读正文，保留段落、编号和来源网址。

## 2026-10-21 — 案件记录编辑体验

- “设置格式”更名为“高级格式设置”；新建记录保持空白，提示文字不会进入正文。
- 重整备忘录、台账的轻磨砂窗口、纸面正文、日期胶囊和紧凑附件操作。
- 查看、编辑、保存以及进出高级格式设置时，保留正文阅读位置。

## 2026-10-21 — 下载点击按安装包系统区分

- 官网访问后台在关键指标下展示 macOS Apple 芯片、macOS Intel、Windows 的下载点击次数、去重访客及点击占比；无点击的版本显示 0。
- 分类取自安装包下载目标，沿用已采集历史数据和时间/设备筛选，CSV 同步列出三个版本。

## 2026-10-21 — 案件记录格式与主表定位

- 案件备忘录和台账支持 Markdown 预览，复用知识库文章编辑器设置格式；格式先应用到记录草稿，点击记录保存后生效。
- 记录正文与完整编辑器共用排版样式，可直接编辑；扩大正文区域，压缩标题、日期和附件区留白。
- 切换系列子案主表编辑状态时保留可见子案位置、横向滚动和阶段筛选。

## 2026-10-21 — 后台六小时使用统计

- 同一设备的应用统计每六小时最多保存一次，新设备首次上报立即记录，重复请求不写入数据库。
- 应用统计“正在运行”改为“六小时活跃”，反映已保存的采样记录，版本与日活也按此频率更新。
- 旧安装包仍按原频率请求；下次发版前需提醒将客户端上报间隔同步改为六小时。

## 2026-10-21 — Windows 完整组件与增量安装验收

## 2026-10-21 · 官网访问与管理后台

- 后台拆分为官网访问、应用统计、系统消息三个导航标签。
- 官网新增匿名访问采集，后台提供时间/设备筛选、趋势、来源、地区、设备与内容关注及下载点击统计和 CSV 导出。
- 官网可关闭访问统计，遵循浏览器隐私偏好；采集不保存 IP 或完整网址，历史数据无法补采。

- 接入固定公开信任根与正式下载清单配置，候选构建包含浏览器、OCR、文档转换器和共享业务服务。
- 增加实际 NSIS 中文路径安装、内嵌配置、Visual C++ 依赖、OCR、PDF、逐页浏览器及匿名升级资料保留检查。
- 修复自检后组件内容变化导致再次启动/更新失败的隐患；激活前再次检查全部文件。
- 国家库旧版 Word 在 Windows 使用随包转换器和独立临时配置，无需另一份全局 Office；Mac 继续优先使用系统 textutil。
- 正式公开发行仍以候选验收与用户授权为前提，实体 Windows 10/11 和真实外部业务流程的验收范围单独记录。

## 2026-10-21 — 安装包资源与功能入口修复

- 修复法答网页面和更新模块漏打包，内置公开问答可离线检索，个人笔记与更新缓存独立保存。
- 修复邮箱附件、发票导出与自动归集、立案证件目录仍指向应用包内部的问题。
- Mac 随包提供通讯录、日历和 Vision OCR 程序，避免使用者缺少开发工具时失效，并补充通讯录权限说明。
- 两种 Mac 包和 Windows 冻结服务统一校验全部页面入口、静态资源及法答网内容；缺失时构建直接失败。
- 修复 Windows 中文页面和设置读取的系统编码依赖；统一 PDF、旧版 Excel、OCR 与诊断依赖，并在冻结服务中实际生成、解析 PDF 验证。

## 2026-10-21 — Intel Mac 安装包

- 新增 Intel（x86_64）Mac 打包路径，与 Apple 芯片版共享程序源码和数据格式。
- 检查应用壳、Python、文字识别及所有随包动态库的目标架构，阻止混入仅支持 Apple 芯片的依赖。
- Intel 版使用独立更新源，避免收到 Apple 芯片安装包。

## 2026-10-21 — Windows 10 兼容与双平台复核

- Windows 安装器接受 Windows 10 1809 及更新版本的 Intel/AMD 64 位家庭版、专业版、企业版，继续支持 Windows 11。
- 修复环境检测失败后重试可能同时执行安装计划、重复订阅进度事件的问题；不支持的系统停止进度动画。
- 修复 Windows 服务启动失败后残留运行状态导致无法重试的问题，退出仍等待资料安全保存。

## 2026-10-20 — Windows 轻量安装器开发版

- 新增 Windows 环境检测、签名组件清单、下载续传、逐文件校验及安装失败保护；业务数据保存在独立用户目录。
- Windows 能力配置去掉苹果通讯录/日历同步、生物识别、Finder 标签、录音、夸克与飞书；Mac 保留原功能。
- 司法短信新增文本/截图预览和确认导入，沿用分析与案件关联，不直接自动写入开庭或待办。
- 新增 Windows 系统文件操作与加密凭据适配、共享系统消息及版本检查入口。
- 当前为隔离开发构建，尚未配置正式 Windows 下载通道或发布安装包；不代表已完成所有 Windows 业务验收。

## 2026-10-20 — 合并邮箱配置入口

- 服务与资料列表合并为一个“邮箱配置”入口，页面内用二级菜单切换三种邮箱。
- 配置表单直接显示在页面内；切换分别保留未保存的填写内容，不自动保存账号或授权。

## 2026-10-20 — 邮箱自主配置入口

- 设置 → 工作空间 → 服务与资料新增企业微信／腾讯企业邮箱、网易企业邮箱和 QQ 邮箱入口，直接打开对应账号配置。
- 配置页提供网页版入口、授权码获取、保存与连接检测指引，复用现有邮箱授权和可选附件会话配置。

## 2026-10-20 — 开庭案号同步到案件详情

- 手动录入、识别后保存、导入、司法短信及系列子案批量创建的开庭提醒，自动合并案号和受理机构到关联案件的“案号”栏。
- 同一案号忽略空格、括号差异去重，补齐空白性质及受理机构，保留原有案号、人工资料和审理节点日期，并记录数据日志。
- 提供预览、备份后补齐历史开庭案号的修复工具；重复执行不会新增重复记录。

## 2026-10-20 — 邮箱新邮件同步

- 修复从首页提醒直接打开的邮件只有正文缓存、缺少列表索引，导致刷新后仍不显示的问题；查收时自动补齐索引。
- 邮件正文与列表并行加载时合并最新缓存，避免较晚返回的正文覆盖已同步的新邮件。
- 邮箱标签页切回前台时重新检查新邮件，前台每分钟自动同步；后台暂停，避免请求重叠。
- 自动同步保留列表滚动位置；同步失败继续显示本地缓存并提示重试，显示最近成功同步时间。

## 2026-10-20 — 临时文件用途与清理建议

- 储存管理新增临时文件逐项明细，显示打包副本、更新工具、验收产物及保留材料的大小、路径、修改时间和清理影响。
- 优先选择旧打包副本；最新候选包提示暂留，SQL、数据库、敏感或未知文件不提供删除。
- 清理改为明确选择及二次确认，核对文件版本和占用状态，拒绝旧版整目录清空请求。

## 2026-10-20 — 统一设置与系统消息

- 管理后台新增系统消息管理，支持纯文字预览、确认发布、撤回和分页查看历史。
- 本地及公开版共用首页系统消息入口，首次打开即清除红点，支持离线查看和联网同步；关闭匿名统计仍可接收。
- 外观与体验统一设置用户名和律所名称、Logo、文号与联系方式，文书预览及导出共用同一模板和资料。问候语默认隐藏，新安装默认称呼为“新用户”。
- 会议室预定与快速报批增加定制提示、明思版本体验入口及不再提示选项。
- 司法短信分析、传票分析接入统一功能模型配置；AI API 管理支持自定义 Chat Completions / Responses 接口和 OpenAI、Kimi 接入向导。
- 修复所函预览空白、文字转义、文号前缀重复以及客户选择组件在窗口缩放时的异常。

## 2026-10-17 — OpenCode Go Grok 4.7

## 2026-10-18 公开下载包隐私隔离

- 公开安装包与本机版本共用同一代码；仅移除公开版的个人中心及家庭财务同步，私有版不受影响。
- 公开包保留本地 OCR 依赖与使用说明书，不再按精简体验版打包。

- 安装包默认使用当前授权品牌标识，移除体验版独有样式覆盖，修复首次启动覆盖默认标识及品牌设置写入只读程序目录的问题。
- 公开体验包将团队身份、证件、联系方式、银行资料及真实客户默认值替换为虚构占位或清空。
- 独立数据目录及虚构案例保留，安装包不附带原始后端 Python 文件；源码仓库保持私有。

## 2026-10-18

- 发票扫描加入附件大小筛选：超过 5 MiB 直接跳过；1–5 MiB 结合发票命名、邮件来源判断。优先读取小附件和正文，避免整封下载大证据材料；ZIP 成员和本机历史文件同样执行大小限制，保留原件。

- 修复发票中心历史邮件受 IMAP 可见范围限制导致的漏票，补查本机已保存且邮件日期可核验的发票。
- 修复 PDF 将税额/零税额误作价税合计；同票 XML 自动补全 PDF/OFD，行程单单独标示且不重复计入金额。
- 扫描改为短批次自动续扫，失败邮件保留重试资格，避免重复扫描无限排队；进度区准确区分扫描中断与下载失败。

- 模型目录与选择器新增 Grok 4.7，保持原默认模型和隐藏偏好。
- 普通及流式回答适配 Responses 接口，保留本地多轮上下文、用量统计和既有备用模型策略；不在远端保存会话。
- 同步前端资源与离线壳版本，避免本机沿用旧列表。

## 2026-10-17 — 修正选中 Skill 后仍超预算

- 身份、记忆和问候等通用问题不再附带无关任务 Skill；保留正常的用户记忆上下文。
- Skill 仅加载完整核心文件，不再递归拼入安装目录、素材和参考文档，也不静默截断核心规则；缺少参考或执行能力时不能声称已经读取或执行。
- 官方 DeepSeek V4 型号采用更合适的保守应用预算，未知供应商和网关保持原限制；保留部署覆盖配置。
- 同步更新本机程序资源与离线壳版本，保留当前 Skill 选择和历史数据。

## 2026-10-17 — AI 增强审查与联网输入优化

- 联网资料改为本地筛选相关原文、保留表格和相邻限制条件、去除重复转载；按问题复杂度和剩余输入空间分配预算，减少整页正文带来的 token 消耗，不增加摘要模型调用。
- 搜索规划采用独立短超时和更小的输出额度，超时改用本地查询，保留指定域名、API 标识及必要续问对象。
- 保留流式失败的具体原因，修复恢复后只显示笼统失败的问题；取消操作必须得到明确确认，连接中断不再把半截回答当作完整结果。
- 文件问答改为按预算检索原文片段，确保每个所选文件都有片段；不能覆盖全部文件时明确拒绝，并提示节选不等于完整审阅。文件失败与停止状态可被恢复流程读取。
- 所选 Skill 在列表加载前也有明确标识，发送前校验残留选择；规则过长时直接提示切换 Skill。生成中禁止删除当前消息或用重新生成覆盖草稿。
- 不支持流式读取的浏览器沿用完整回答接口；更新前端与离线程序缓存版本，保留历史、草稿和离线案件数据。

## 2026-10-17 — DeepSeek V4.1 Flash 1017

- AI API 管理与 AI 增强模型选择器中的官方 DeepSeek Flash 显示为 V4.1 Flash 1017；调用继续使用官方滚动模型 ID `deepseek-flash`，已有模型偏好无需迁移。
- 保留 OpenCode Go 默认路由及模型选择；网关未公布具体快照，因此其名称不标注未经确认的 1017 版本。

## 2026-10-16 — 移动端效率中心全屏布局

- 效率中心改为覆盖完整可用屏幕的面板，固定标题、编辑/关闭按钮与五类分组定位；工具入口按双列卡片排列，内容独立滚动。
- 长名称和副标题换行，编辑模式使用单列；支持手机横屏、平板触控、明暗主题和安全区。
- 打开后隔离背景交互，关闭恢复原页面，支持键盘退出与焦点循环；离线壳和启动资源版本同步更新，不清除业务缓存。

## 2026-10-16 — 移动端离线启动与详情操作区

- 修正侧栏脚本与离线资源清单的版本不一致，恢复断网启动、主页导航及已有案件缓存读取；保留本机离线数据和待同步操作。
- 案件详情的文件夹/文书操作按钮和底部操作支持窄屏换行，长名称不再撑出操作区；案件工作区高度随移动浏览器可用高度调整。
- 修正平板窄屏下 AI 工作区与工具栏溢出，历史列表改用覆盖布局，保留对话正文可用宽度。
- 增加启动资源缓存一致性检查及多尺寸、明暗主题、独立存储离线启动浏览器验证。

## 2026-10-16 — 启动、响应与后台资源体检修复

- 减少启动时的重复初始化与首页重复请求，案件离线快照改为批量读取，未变化的文章关联复用扫描结果。
- 保留浏览器缓存，静态资源压缩并按需加载 AI 功能；支持就绪即进入界面，同时保留已有启动图时长设置。
- 非活动文件页停止目录监听，后台轮询避免重叠；图片及系统文件操作不再阻塞主服务。
- 直接问 AI 支持逐段显示正文，完整回答继续按原规则保存；AI 连接复用并隔离后台整理任务。
- 收窄搜索索引更新范围，提供先备份、保全异常记录再整理数据库的维护工具，以及保全记录导出和重新关联页面。
- 性能诊断区分本地接口、外部请求及长连接，补充事件循环延迟和 WebKit 不支持的统计说明。

## 2026-10-16 — 案件记录长附件排版修复

- 修复 WebKit 中长附件名、路径撑宽内容区，导致标题和正文被裁切的问题。
- 附件名称与路径最多展示两行，窗口固定左右留白，仅纵向滚动；查看与编辑保持一致布局。

## 2026-10-16 — 案件备忘录、台账附件与统一窗口

- 案件详情中的备忘录、台账支持添加多个附件、绑定本地文件或文件夹，保存后可下载附件或打开绑定位置。
- 文件和绑定随记录一起保存；取消编辑不提交变更，解绑保留本地原文件，上传失败保留草稿。
- 两类记录统一采用磨砂玻璃窗口，查看与编辑保持相同窗口、文本框和附件布局，适配明暗主题及窄屏。

## 2026-10-16 — AI 记忆审查修复与对话后台生成

- 回答生成时可以切换或新建对话，最多同时生成 4 个回答；各对话保留草稿、独立进度及停止操作，刷新后可恢复多个任务。
- 修复“不记忆”信息经后续回答间接进入召回、上下文刷新掩盖聊天版本冲突、记忆修改清空对话摘要等问题。
- 修复历史上下文排序、旧浏览器记录导入版本、无效模型返回误报完成，以及重建摘要重复运行全部已完成任务的问题。
- 记忆与上下文采用磨砂浮层、分段导航、可展开来源卡片和固定操作栏，适配明暗主题、窄屏及辅助功能偏好。
- 重启脚本支持登录后的源码校验，避免把未登录响应误判为启动失败；桌面入口统一使用校验结果并支持配置端口，异常配置和响应有明确失败提示。

## 2026-10-15 — AI 增强记忆与上下文

- 个人与案件记忆分开管理，支持来源定位、停用、冲突确认和变更记录。
- 新消息支持对话摘要、同案相关历史召回与上下文查看、排除及修正。
- “本次不记忆”保留当前连续问答，禁止长期记忆读写与跨对话召回，并永久排除该轮自动提炼。
- 历史保存增加版本冲突保护，旧聊天不参与自动整理；后台任务可重试，输入超限明确提示。

## 2026-10-15 · 案件关联知识复核与界面优化

- 修复已有全文命中时漏掉关键词补充结果，以及逐篇分析偏向前序材料的问题；研究问题上限扩展至48项，超限明确提示，逐篇分析范围写入核验底稿。
- 修复更新文章状态会收起阅读上下文的问题；后台页面停止发起非必要状态读取，拒绝布尔值冒充文章编号。
- 工作台关联知识采用磨砂统计栏、清晰正文卡片和折叠研究设置，优化信息层级，适配明暗外观、键盘焦点及减少透明效果。

## 2026-10-15 · 案件关联知识

- 办案工作台新增“案件关联知识”：提供文书或证据后，从现存知识库推荐支持论证、风险提示及程序取证参考文章，逐篇展示用途、适用边界和文章／案件两侧原文。
- 支持查看文章上下文、回看案件材料、主动加入案件研究、调整研究问题新建分析，以及下载 Word 报告与核验底稿。
- 保存分析快照，文章修改或删除后仍可核对历史依据；显示候选范围、正文不足及部分失败，不自动联网或把文章观点当作现行法律。

## 2026-10-15 · 储存项目细分

- 将其它项目文件拆分为 AI 运行程序、下载中心、发票归集包、邮件发票记录、验收截图、数据库事务文件、功能数据和部署许可文件，提供逐文件路径与大小明细。
- 验收截图支持逐项选择、二次确认后清理；业务资料、运行程序和数据库附属文件保留保护。未知文件可查看明细。

## 2026-10-15 · 微信公众号图片正文收录

- 修复纯图片文章被当作来源说明或尾图而拒绝收录的问题；静态与动态抓取均在质量检查前识别图片文字，并保留原图供核对。
- Playwright 缓存浏览器缺失时自动尝试本机 Chrome；图片文字优先使用现有本机中文识别，超长图分片、Tesseract 兜底，识别在工作线程执行。
- 修复懒加载占位图被当作正文图片的问题；不再只识别前 6 张图片，超过单次 40 张上限时明确提示分批导入。

## 2026-10-15 · 文章标签编辑

- 文章阅读页的标签编辑改为磨砂玻璃浮层、双栏内容和固定保存栏；窄屏自动改为单栏，支持深色外观、减少透明效果和键盘焦点循环。
- 领域与子分类显示已选数量，支持子分类搜索；删除领域同步清理对应子分类。已有标签按使用频次展示，支持搜索和逗号批量添加，作者标签单独只读展示。
- 新增未保存提醒、放弃修改确认和快捷保存，保存期间阻止重复操作；失败保留填写内容，保存对象锁定为打开编辑时的文章。

## 2026-10-15 · 点击文章标签筛选

- 首页文章列表中的专业领域、子分类和自定义标签均可点击，跳转到带有该标签的全部文章列表；清除原搜索和其他筛选并回到第一页。
- 标签点击和键盘操作不会打开文章，展开状态下的标签同样支持筛选。

## 2026-10-15 · 知识库文章标签栏

- 首页列表和两种文章阅读页统一为单行 2:1 布局：左侧标签，右侧作者、日期及来源。
- 标签栏上下留白对齐，按标签实际行高裁切，避免折叠时露出下一行。
- 标签过多时悬浮平滑展开、移开收起；保留点击固定展开、键盘操作和减少动态效果支持。首页完整展示专业及自定义标签，来源可直接打开。

## 2026-10-15 · 办案工作台入口

- 效率中心案件分组新增“办案工作台”，副标题“证据 事实 时间轴”，默认位于案卷归档工作台上方；既有排序首次加入新入口时同样放在归档入口前。
- 保留案件详情入口和按案件复用标签页；页面与通用标签名称统一为办案工作台。

## 2026-10-15 · 办案工作台布局与材料选择

- 压缩顶部说明，案件输入与事项切换底部对齐，统一材料及办理卡片的宽度、间距和标题节奏。
- 修复材料用途菜单向左超出嵌入窗口的问题；菜单按窗口边界定位，适配矮窗口、键盘导航与明暗外观。
- 按核对、时间轴、编排分别提供明确的添加动作、材料示例及单份／多选说明，时间轴不再将事件材料误称为候选证据。
- 以匿名材料复测选择、核对、编排、时间轴保存与导出，保留原有归档选择协议。

## 2026-10-14 · 时间轴样式与尾注导出

- 导出前可切换纵向时间轴、精简对照表、纪事卡片，提供前8项已保存事件的实际预览，设置随成果版本保存。
- 增加显示／隐藏原文依据选项；Word采用正文上标与原生尾注，相同引句复用尾注，隐藏时不生成引用编号及尾注。
- 正式时间轴去掉复核状态列与重复定位提示；排除事件不进入交付文档，完整复核及原始依据仍在工作台和核验底稿中保留。
- Word、PDF、SVG布局同步；Excel保持清晰事实表，Markdown以尾注方式列示选定的依据。无需再次调用AI即可切换样式生成新版本。

## 2026-10-14 · AI 账户余额

- AI 增强和案件 AI 管理在模型选择器旁显示当前 API 服务账户余额，支持 DeepSeek 官方及硅基流动，其他服务不显示。
- 打开页面、切换模型、完成问答和返回前台时刷新；可见页面每 30 秒更新，点击余额可立即刷新。隐藏页面停止查询，查询失败隐藏数值，避免显示其他账户或过期余额。

## 2026-10-14 · 出处标签与定位纠正

- 原文依据改用“引文1／材料1”中文标识，明确引句与来源文件的对应关系。
- 纠正将约3500字文本片段标成原件段号的问题：无可靠页段位置时明确提示按引句查找；旧任务保存导出时不再将此类片段显示为“第1段”。
- 新 Word 材料优先转换为 PDF 后按页提取，标明“转换后PDF第几页”；转换不可用时保留文本并明确未取得原件定位。材料检索缓存升级后按需重建。
- 工作台原文预览复用可验证的页面图像，保留原件下载入口。既有任务、引句和历史成果保留。

## 2026-10-14 · 时间轴 Word 导出重排

- 事实经过表采用日期、事件和复核状态的清晰列式排版，统一 A4 页边距、字体和分页，跨页重复表头。
- 逐字引句移入编号对应的原文依据部分，来源文件集中列示；复用同一引句的事件保持各自独立，所有日期、内容、出处和复核意见保留。
- 已有时间轴任务保存复核即可生成新版导出，无需再次调用 AI；旧成果版本继续保留。

## 2026-10-14 · 办案工作台复审与阅读优化

- 事实核对和证据编排保存时补齐导出后的原件哈希及案件绑定校验，原件在导出中变化时拒绝发布新成果；异常复核状态明确提示。
- 事实核对导出移到后台执行，避免文件生成阻塞服务；保存结束后重算编册按钮状态，防止页数快速读取造成按钮长期不可用。
- 成果区前移到办理记录上方，首次完成收起输入区；导航增加磨砂玻璃层次，正文保持清晰，时间轴复核布局与选中状态更明确。
- 增加导出期间原件变化、事件循环响应及异常参数回归，匿名浏览器复测三项完整办理流程和明暗模式。

## 2026-10-14 · 案件事实时间轴

- 案件办案工作台新增“案件时间轴”：选择事件材料即可提取日期、主体、事件与原文位置，参考法律文书可选。
- 日期保持日、月、年、期间或不确定精度；无有效逐字引句的事件不发布，同事项日期差异及重复记录作为候选供人工核对。
- 支持确认、修订、排除和按原文补录；保存时校验材料版本及成果版本，保留原始提取与历史导出。
- 导出 Word、Excel、Markdown、JSON、SVG 与 PDF，复用案件隔离、材料快照、任务停止和检查点恢复。无需数据库迁移。

## 2026-10-14 · 案件 AI 资料与回答格式修复

- 按案件归属字段与多层外键关联自动发现检索范围，补齐案件台账、备忘录、研究资料、关联文章、收入及阅卷记录等；聚焦案件时自动读取研究正文并提供来源链接。
- 答复前要求核对内部意见与备忘录，长正文和部分记录继续分页；查询轮次达到上限时明确说明未完成范围。
- 修复最终回答 JSON 包装未解析造成的段落堆叠；历史回答显示、复制及导出同步恢复正常格式，并保留分段编号列表的起始序号。

## 2026-10-14 · 扫描盘取件进度提示

- 下载到本机、归入案件和发送至 AI 时，在操作区持续显示进度条、扫描件数量和页数；取件期间防止重复提交。
- 打印机未返回完成比例时显示不定进度，下载交接阶段显示当前状态；完成和失败保留清晰反馈，支持深色模式及减少动态效果。

## 2026-10-14 · 总览卡片消失修复

- 修复应用进入后台后活动状态无法恢复的问题，回到前台时恢复当前页面动画与定时任务，未选中的标签页继续暂停。
- 总览卡片直接可见，不再依赖入场动画完成；动画暂停或取消也不会留下空白卡片区。
- 更新前端及离线外壳资源版本，并增加前后台切换、分类切换、反复开关和动画暂停回归验证。

## 2026-10-14 · 扫描件归入案件

- 扫描盘选择案件并点击“归入案件”后，直接将 PDF 保存到绑定文件夹的“#下载材料”，使用统一案件材料保存与索引流程。
- 保存前校验绑定目录，避免重复归入和同名覆盖；页面显示下载中状态及保存位置。

## 2026-10-13 — 发票中心全流程复核

## 2026-10-14 · 事实核对与证据册

- 案件详情与右键菜单新增办案工作台，支持逐条事实初核、原文定位、律师复核和成果版本。
- 已确认的证据顺序可生成带页码与书签的证据册、Word/Excel目录及原件页码映射。
- 原件只读；任务支持停止、继续、重启中断识别，材料变更和同名成果不会静默覆盖。

- 三种邮箱按批次续扫完整日期范围，较早邮件不再被数量上限截断；自动归集继续剩余批次并在失败后间隔重试。
- 修复红字金额负号丢失、XML 税额合计、不同文件夹相同邮件编号误分组，以及同票多格式/转发副本的重复选择。
- 修复表头式 CSV 和图片发票的元数据识别，复用本机 OCR，并用大写人民币总额恢复无法读取的小写金额。
- JPG 筛选包含 JPEG；补齐无文件名附件，损坏 ZIP 不再拖累同封邮件的其他发票；普通文档只在暂存中判断。
- 邮箱切换隔离迟到的扫描、历史和自动归集响应；扫描缓存独立于邮箱摘要、原子写入，并处理邮件编号重置。
- 导出完整打包最多 5000 个选中文件，拒绝缺失或跨邮箱文件；后台打包不阻塞界面，导出历史按票号/内容识别副本并兼容旧记录。

## 2026-10-13 — 正文发票链接自动恢复

- 自动解开诺诺二维码图片地址中的真实领取链接，并与正文已有链接去重；旧扫描缓存直接兼容。
- 接通票通动态领取页的官方查询和下载接口，支持 PDF、OFD、XML 格式。
- 自动读取链接下载的 ZIP 内全部已选格式发票，沿用压缩包大小和路径安全限制。
- 校验实际文件内容，避免将链接错误页面保存成发票。

## 2026-10-13 — 发票扫描遗漏修复

- 三种邮箱覆盖自定义文件夹等全部可读取目录，隔离目录内相同邮件编号的缓存和文件。
- 修复通用或数字附件名、分段编码文件名、压缩包内发票和附件与正文链接并存时的遗漏；同名链接文件分别保存。
- 读取失败不再缓存成无附件；超时后再次扫描优先处理未完成邮件，并保留已找到结果。
- 扫描告警同步显示在发票中心、下载中心和自动归集历史，部分完成不再显示为全部成功。

## 2026-10-13 — 区分系统登录与外部服务登录失效

- 修复一张网“申请详情”、开放目录、下载、同步等操作因法院会话失效而误跳 Stella 登录页的问题；保留法院官网返回的实际提示。
- 案件页共享接口处理不再把业务权限错误当作断网或吞入离线缓存；系统会话真正失效时仍正常进入登录。
- 更新离线页面资源版本，保留本地案件缓存和待同步操作。

## 2026-10-13 — 事项本地文件区域样式修复

- 补齐事项详情中本地文件的空状态、绑定按钮、文件卡片与路径输入布局，统一间距和提示层次。
- 修复绑定按钮误用表格文字操作样式的问题，支持深色模式、键盘焦点和窄屏换行；更新离线页面资源版本。

## 2026-10-13 邮件团队成员标注

- 邮件支持勾选多封、右键单封及正文旁标注团队成员，名单直接同步文书生成工具律师库。
- 增加全部成员、未标注及指定成员筛选，可取消或更换标注，刷新后保留。筛选范围为已加载邮件。

## 2026-10-13 — 事项操作栏与文件快捷打开

- 待办、开庭、保全和上诉／异议列表为操作栏保留固定宽度，压缩其他列的空余空间；按钮保留间距和点击区域且始终单行，窄窗口支持横向滚动。
- “本地文件”在只绑定一项时直接打开；多项绑定显示选择菜单，未绑定时进入绑定区域。菜单支持键盘和失效位置提示。

## 2026-10-13 — 修复事项文件入口跳转登录

- 已登录的本机 Stella 在私密访问模式下可正常管理事项文件绑定；远程或代理请求仍不能操作本机文件。
- 权限拒绝显示实际原因，不再误跳登录页；真正的登录失效仍进入登录流程。

## 2026-10-13 — 事项独立绑定本地文件

- 待办、开庭、保全和上诉／异议事项可分别绑定多个本地文件或文件夹，通过系统选择器或粘贴路径添加，在事项详情点击打开。
- 绑定独立持久保存，路径失效时明确提示；解除绑定和删除事项均保留原文件。

## 2026-10-13 — 下载中心紧凑排版

- 下载概览收为标题旁的轻量数字，来源筛选与搜索整合为磨砂玻璃工具栏，减少顶部占用，让文件列表更早进入视野。
- 刷新、阅卷任务与更多操作分层呈现，清理记录收进菜单；保留案件、用途、位置与进度信息，并适配深色、窄屏、键盘操作及减少透明度设置。

## 2026-10-13 — 备忘录编辑与阅读样式统一

- 保存备忘录后直接显示已保存内容；取消已有备忘录的修改后返回原内容的阅读模式，保持备忘录打开。
- 备忘录标题、记录日期和正文在阅读布局原位置编辑，统一正文的字号、字重、行距和背景，长内容随弹窗滚动。
- 打开备忘录时取消底层详情遮罩与面板阴影的叠加，消除两侧透出的深色框线。

## 2026-10-13 — 下载中心与材料归集升级

- 网易企业邮箱、QQ邮箱、一张网、司法短信、五类文书生成、AI增强与发票中心补齐统一进度提示；已知大小显示实际字节，未知大小显示动态状态，准备、下载、保存、完成与部分失败分别提示。
- 下载中心统一展示来源、用途、获取批次、具体案件和真实保存位置，支持搜索、来源与状态筛选、分页、重新下载、打开位置和确认存入案件；既有司法文书与卷宗记录汇入，旧浏览器记录保留明确的位置确认状态。
- 邮箱附件下载前明确选择发票、案件材料或其他附件；案件材料确认已绑定文件夹后写入独立子目录，普通附件不再混入发票目录，绑定失效时保留暂存文件并提示失败。
- 原生系统保存窗口增加实时进度回传，完成后核对用户选择的真实路径；大型卷宗 ZIP 保留原生流式交付。需要重新启动 Stella 激活原生更新。
- 清理已完成记录不删除实际文件，未关联或待确认的案件材料继续保留；原有卷宗暂停、继续和重试入口继续可用。
## 2026-10-13 — 电子送达归档文件夹

- 默认归档目录改为 `#Stella电子送达归档`，创建或迁移时标记为访达“重要”红色标签；保留其他标签。旧 APEX／法院文书目录兼容迁移，同名文件保留并同步归档索引。

## 2026-10-13 — 司法短信下载进度

- “自动获取全部”增加实时进度条，显示当前文书、下载大小和完成数量；总大小未知时显示动态进度，完成、部分失败和验证要求分别提示。下载期间禁止重复点击，关闭详情或切换到后台时暂停进度查询。

## 2026-10-13 — 司法短信大文件文书

- 司法短信送达文书与短信附件的单文件上限从 50MB 提高至 500MB；自动获取、手动导入及浏览器下载采用同一上限，保留地址安全与文件类型校验。

## 2026-10-12 — 私密 Mac 体验包

- 新增不包含既有业务数据、个人财务或已配置密钥的 Apple 芯片独立体验包；接收者可自行配置 AI API、MCP 与 Skills。
- 初次启动自动生成两个虚构案件与三篇原创示例文章，使用独立数据目录；干净安装的首页显示 Stella 字标。

## 2026-10-12 — 用户长期记忆

## 2026-10-12 源码公开与下载准备

- 增加署名示丁某律师、禁止商用、禁止修改的源码公开许可证，并保留第三方材料的原有许可。
- 首页增加源码 ZIP 一键下载入口和独立下载、安装说明。

- 修复较早安装长期记忆功能的数据库缺少版本字段、导致问答返回 500 的兼容问题；升级保留已有记忆与开关设置。

- AI 增强与案件 AI 新增长期记忆管理，支持搜索、添加、编辑、单条删除、清空、使用开关与自动保存开关。记忆跨对话保存在本机，与聊天历史独立。
- 支持“记住：……”和“忘记：……”指令及查看全部记忆；自动保存简短明确的称呼与回答偏好，保存后提示。
- 增加“本次不记忆”，暂停本次读取与保存；不会自动挖掘旧聊天、案件文件或网页。

## 2026-10-12 · 案件 AI 常用工作

- 修复聚焦查询仍混入其他案件的来源问题：后端按所选案件及实际子案限定只读资料；未关联的一张网资料另行核对。
- 旧回答中涉及多个案件的来源提示重新核对，大量案件链接默认只显示前八项，可按需展开。
- 时间线改为按日期排序的案件进展表，日期不明事项、系统建档／编辑／同步记录分别列示，明确事件案号和依据。

- 增加案件聚焦入口：按具体案件持续追问、核对一张网与查看案件，各案件对话分开保存。
- 修复聚焦切换失败恢复、重新搜索案件后的旧选择残留，以及待办保存期间仍可编辑的问题；保留选中回答摘录。
- 案件 AI 回答可整理为待办草稿，优先带入选中文字；用户选择案件并填写事项、提醒时间后明确保存，沿用案件管理待办。

- 新增九个快捷查询：今日工作、开庭准备、待办期限、立案补正、送达消息、案件关联、案件分工、费用回款与工作周报。
- 支持在办／含已归档范围及 7／30／90 天时间范围，点击填入可编辑问题；空白对话只显示欢迎页面板，开始对话后才显示“常用工作”折叠栏，避免重复入口。
- 快捷问题明确数据缺失、已登记期限、一张网同步时间和未关联记录的核对口径；沿用只读查询与来源跳转。

## 2026-10-09 · CC2API 接入

- AI API 管理与 AI 增强增加 CC2API Claude 网关及其模型目录，支持 Messages 协议和本机密钥配置。
- CC2API 通过官方 Claude Code 无交互客户端调用，兼容仅限 Claude Code 的密钥分组；连接检测与 AI 增强共用接入路径。
- 客户端独立配置、禁用额外工具与非必要流量，不保存问答会话；取消或超时会停止调用进程。

## 2026-10-08 · 在线阅卷与卷宗下载进度

- 卷宗下载进度归入“一张网”标签组，全览分组及组内关闭全部同步更新。

- 下载进度页采用克制磨砂玻璃、紧凑统计与独立文件区；优化长名称、窄窗口和浅深色排版，选中任务使用淡色底与细边框。完成任务显示 ZIP 大小与就绪状态，单页列表隐藏分页按钮。

- 一张网新增在线阅卷：查看申请、状态、有效期、关联案件和开放卷宗目录，支持官网申请入口。
- 卷宗支持后台流式下载与 ZIP 打包，保留原始目录和文件清单；支持暂停、继续、取消、失败重试和服务重启恢复。
- 新增独立卷宗下载进度页，显示文件大小、数量、下载速度、百分比及逐文件状态；下载中心增加入口。
- 申请材料可创建明确标记的打包测试任务；不混入正式开放卷宗。

# APEX Changelog

## 2026-10-08

- 首次打开一张网即加载在线阅卷总数，无需先点击阅卷标签；搜索和状态筛选不再改变导航中的阅卷总数。

- 文章正文页将来源、作者、日期及编辑标签入口独立于可折叠标签栏；标签收起时仍完整保留文章信息，窄窗口自动换行。

- 一张网手动打开法院诉讼服务网时保留 Chrome 登录窗口显示；切换账号优先停止旧账号登录、同步和保活任务，立即显示目标账号的信息。

- 分类管理将“历史整理”改为“重新分类”，说明采纳新分类后会自动归类旧文章；批次预览只统计真实领域及子分类差异，展示具体增删，跳过无变化文章，并修复检查下一批不前进的问题。
- 文章正文标签栏与列表卡片默认只显示一行，溢出时可点击展开完整标签并再次收起，保留正文阅读空间和列表密度。

- 文章正文标签栏和知识库文章列表显示已确认的专业领域二级分类，标明所属一级领域；兼容旧版离线快照，排除人工取消或已删除的分类。

- 目录管理拖动一级领域或自定义库时临时收起全部二级目录，松开或取消后恢复；缩小排序页字号与行距，提高同屏内容量。

- 目录管理新增可见拖动手柄、精确插入位置和列表边缘自动滚动；松开即时保存，同级排序支持键盘移动及移到首尾，移除逐项上下按钮。

- 修复正文编辑器 A4 分页的跨页文字、异常留白及后续段落错位；支持长段落、嵌套列表、表格及图片，保留选区和正文内容，窗口、字体及图片变化后自动重排，专注模式保持纸张宽度，并修复深色纸张显示。
- 智能目录支持“案例编号（入库编号）”与案名分段的典型案例汇编，按正文生成完整案例及各案例栏目导航。

## 2026-10-07

- 知识库目录悬停一级分组时显示二级目录；停留在具体二级目录后才显示其子标签。快速掠过不会误展开，离开后短暂延时收起，触屏和点击模式保留箭头操作。

- 修复 Safari 添加到桌面后仍启动独立案件页的问题：新安装从主界面启动，旧桌面入口接入原有底部悬浮导航；应用壳 v232 在独立存储环境完整准备主页缓存，缺少登录时显示登录流程，案件内嵌页登录失效时跳转整个 App。

- 移动端旧案件入口接回主界面标签容器，复用已有底部悬浮导航及返回主页功能；应用壳 v231 同步缓存主页及必要资源，支持断网返回与刷新。未登录或缓存未完成时不把登录页当作主页，保留案件快照及待同步操作。

- 移动端安装名称、图标和启动品牌更新为 Stella；桌面品牌设置同步到手机，离线保留最近品牌。升级移动应用壳至 v230，品牌图片和清单重新验证缓存，保留案件缓存及待同步操作。

- 桌面设置页缩减过大留白，统一分组标题、分隔与控件间距；配色选项在大窗口使用三列，窄窗口保留两列，并修复原生窗口中设置入场动画停滞导致不可见的问题。

- 知识库目录统一紧凑行、缩进、数量及选中样式；新增目录搜索和统一「目录管理」入口，专业领域、自定义库及作者均支持即时管理。
- 设置新增悬停或点击展开方式，保留目录展开路径；搜索临时展示命中路径，清空后恢复。
- 二级分类可保留文章关联改名；删除继续保留文章并抑制同名自动建议。目录管理支持拖动与上下移动排序、影响确认、失败保留输入及联网提示。
- 修复快速切换分类显示旧结果、保存视图遗留子分类、离线子分类筛选失效、目录重绘收起、损坏缓存中断初始化，以及删除后刷新失败恢复旧目录的问题。排序拒绝过期或重复目录，避免部分写入。

## 2026-10-06

- 统一在办案件候选菜单：案件管理中的待办、开庭、保全、上诉/异议期限、司法短信、法院官网记录及团队收支，案卷归档、个人收入、扫描件归档、知识中心、文章关联、AI问答关联和案件文件选择共用同一组件。支持常用优先、最近更新、案件名称和按客户归类，记忆排序和最近选择；系列子案显示完整名称，长名称自动换行。候选数据分页加载，列表分批展示。

All notable user-visible changes are recorded here. Internal refactors are only
listed when they affect compatibility, reliability, or future maintenance.

## Unreleased

### Added

- 知识库专业领域支持自动归类与二级子分类：新旧文章均可依据内容自动提出具体子分类，规则不足时调用已配置的 AI；用户确认建议后自动匹配相关文章，无需逐一手动创建。保留人工修正、历史整理预览及子分类和自定义标签的手动排序。
- 知识库新增文章回收站：单篇和批量删除会保留可恢复快照30天，支持恢复、单独或批量彻底删除及一键清空；到期后后台自动清理，原始上传文件不受影响。
- 品牌标识新增本机历史管理页，可预览、重新应用或单独删除曾上传的标识。
- 设置新增「备份管理」：可调整自动备份的每天、工作日或每周计划、执行时间与数据库保留天数，查看空间占用，并单独或批量删除数据库及上传文件备份。
- 效率中心编辑模式支持将功能入口拖到其他类别并调整位置，也可逐项修改副标题；保存后同步显示在展开菜单与快捷工具区，取消编辑会恢复原设置。
- 效率中心「案件」新增案卷归档工作台：按律所诉讼和非诉样本、法穿刑事清单核对本地案件材料，生成页码与目录一致的电子案卷，并保留独立导出版本。

### Changed

- 补齐刑事法律、侵权责任、婚姻家事、物权、民事诉讼法、民商事审判、执行异议与复议及再审等领域的二级主题识别；升级时补充旧文章的分类建议，保留人工归类与排除项。多领域文章逐一检查二级分类，AI 补充时保留已识别的分类。

- 智能分类的「分类目录」可手动删除二级子分类，并显示关联文章数。删除后文章保留、分类关联移除，自动分析不会重新建议已删除的同名子分类；仍可手动重新创建。
- 修复已保存视图在编辑模式下显示拖动图标代码、导致视图名称重叠的问题。
- Stella 在设置中更换品牌标识时继续实时更新 Dock 图标；新图标采用与应用包相同的尺寸、留白、圆角和多分辨率图标生成流程。重新保存或编码的同款品牌图会沿用内置图标。
- 智能分类将历史 AI 建议中明确同义或同主题的单篇表述归并为可复用主题，再按不同文章计算支持数；升级前自动备份数据库，原建议保留，无法可靠归并的争点仍不进入审核。
- 智能分类建议只在至少两篇文章共同涉及、名称足够简明时进入审核；AI 不再把单篇文章的具体争点建议为二级分类。既有单篇简明建议保留作后续匹配，过细建议不再占用审核列表。
- 知识库智能分类弹窗改为建议审核、分类目录与历史整理三个视图；多篇涉及优先、搜索和分批加载让大量建议更容易审阅，已确认分类仍可排序。
- 修复自定义主题下 AI 增强历史侧栏的选中对话被主题实色填充、文字难以辨认的问题；选中态改用浅色主题底纹。
- Stella 桌面版升级后默认恢复“跟随系统”明暗模式；设置的“外观与体验”可明确选择跟随系统、浅色或深色，系统外观切换时自动同步所有内嵌页面。
- Stella 案件管理列表的右键菜单现提供查看案件详情、打开案件文件和案卷归档；页面空白处提供当前页面常用操作，并更新离线缓存以避免继续显示系统的帧框菜单。
- 修复黑夜模式欢迎页短暂显示黑底后又变白的问题：启动期间固定沿用最初识别到的明暗主题，页面退出后再清理启动标记。
- 黑夜模式下侧边栏、顶部导航、AI 欢迎页、品牌设置与启动页的 Stella 标识保留红色末字母，浅色笔画更清晰，并带轻微静态暖色光晕；启动页随黑夜模式显示黑色背景。
- Stella 各内部页面右键按当前功能显示快捷操作，并复用页面按钮的可用状态；案件列表行、案件文件及归档选择另有对应操作，空白处不再显示 WebKit 的“在新窗口中打开帧框”。
- 「总览」页面将 Stella 品牌标识与标题并排展示，自动裁去标识透明留白、提亮深色文字且保留红色笔画；页面卡片按三列填满内容区，分类导航采用紧凑的磨砂玻璃视觉。
- 「总览」页的 Stella 标识提亮红色笔画，在字母背后加入克制的固定暖色柔光，并微调分隔线两侧间距；无需持续动画。
- 微调首页侧边栏横向品牌标识的位置，使其视觉中心更贴近标题中轴线，左端与下方名言对齐。
- 知识中心的导航栏和查知识搜索栏共用实色吸顶区域，搜索栏与菜单保持间距，滚动内容不再从两栏之间透出；最近搜索列表固定显示在搜索框下方。
- 顶部标签栏的品牌标识仅在侧边栏收起时显示，并以平滑过渡展开或收起；点击仍返回首页。
- 修复知识库回收站与删除确认弹窗背景缺失、内容直接透出到遮罩上的显示异常。
- Stella 在源码更新导致本地服务短暂重启时显示等待页，并在服务加载新版本后自动恢复，不再把 503 状态信息当作整个页面展示。
- 修复债权人会议短信因提及“获取验证码方式登录”而被误判为验证码短信的问题，并补扫此前被过滤的记录。
- 司法短信现可识别企业管理人发送的债权人会议通知，提取会议时间和管理人；重新扫描会补入近期曾被误判为无关的短信。
- 知识库正文编辑器修复分页版心定位、长段落跨页、保存期间继续输入与旧草稿冲突；标题、正文和每篇文章的页边距现一并保存，Word 导出保留标题、表格、列表和本地图片。
- 修复运行中的 Stella Dock 图标比关闭时偏大、圆角不一致的问题；当前打包标识直接沿用应用图标，其他上传标识使用相同的留白和圆角画布。
- 放大启动页和首页侧边栏的 Stella 标识，侧边栏标识与名称整体左移并沿侧边栏中线对齐；侧边栏标识再放大 20%，顶部标签栏标识略微右移并作为首页入口，隐藏重复的“全部知识”标签及首页标题旁的 Stella 标识。
- macOS 安装包更名为 Stella，采用当前 Stella 品牌图标；“关于”窗口备注改为“Stella 法律操作系统”，保留原有应用身份标识和本机数据。
- 品牌标识改为上传一张透明 Logo 后全局应用于侧边栏、顶部导航、启动页和 AI 增强首页，黑夜模式继续自动反色；运行中的 macOS Dock 图标和浏览器标签图标也随之更新。
- 知识中心检索只把实际命中关键词的结论列为结果，当前案件只调整命中项排序；搜索页显示案件上下文、真实总数并支持加载更多。日常列表折叠完全重复的结论，排除超出有效期间的结论；跨任务重复提取也会复用同一来源的相同结论。
- 知识中心的“基于此提问”现可打开 AI 增强并填入问题；审核动作先保存当前修改，“复制规范引用”包含核验原文，重复加入案件研究会同步已更新的结论和依据。
- 案卷归档工作台的案件下拉列表改为不透底显示；材料选择直接使用案件文件管理的分栏浏览、搜索、多选和预览界面，并在其中提供归档入口。
- 案卷归档工作台优先展示系列子案的真实名称；案件材料按文件夹浏览、关键词搜索和多选批量归档，已入卷文件可在清单中展开预览。常缺材料预设为不适用并可逐案切换；诉讼和非诉案卷导出时套用律所样本自动生成卷内目录和办案小结。
- 案卷归档工作台新增“保存归档清单”，将当前清单和文件分类快照写入本地 SQLite，支持回看和下载，不会生成电子案卷；电子案卷导出历史也保存在本地数据库。
- 归档所选文件时直接从文件浏览区的磨砂下拉菜单选择类别；归档页收敛为苹果风极简层次和轻玻璃表面，保留清晰的材料列表与明暗主题。
- 展开归档清单类别后，可逐份预览或将已入卷材料移回“待核对”；移出只调整归档状态，原案件文件不受影响。
- 开庭通知识别改用统一 AI 调用器关闭 DeepSeek Flash 思考模式，避免推理内容挤占结构化结果输出；模型返回空内容或无效 JSON 时会再修复重试一次，文书内的指令按原文内容处理。
- 一张网登录时，受控 Chrome 窗口在两种启动路径下都会最小化；即使此前曾手动唤回原生窗口，重新点击登录也会先收起窗口并恢复 APEX 前台显示，避免登录过程把用户切到独立浏览器窗口。
- 一张网登录恢复 APEX 前台时优先使用 macOS 应用激活接口，并移除会触发 Chrome 安全提示的自动化命令行标记。
- 手动唤出法院官网 Chrome 完成登录后，后端会立即最小化受控窗口并将 APEX 带回前台；后台定时登录不再切走用户当前应用。
- 修复 Chrome 最小化后露出桌面或其他应用时 APEX 未回到前台的问题：从 APEX 发起登录会在隐藏受控窗口的同一请求中激活 APEX，并在登录期间持续保持其前台显示。
- 修复一张网登录页加载后因旧变量引用而提前中断的问题；现在先准确切换“律师用户”，再进入账号、密码和验证码流程，失败时不再把旧令牌误报为登录成功。
- 重构邮箱页（QQ邮箱/网易企业邮箱/腾讯企业邮箱共用）视觉：苹果风极简液态玻璃质感，统一描边 SVG 图标与 4px 间距栅格，色彩收敛为单一主题强调色（写信/发送主按钮、发票中心改为 tonal 次强调），列表改为圆角行卡片，写信弹窗改为高斯模糊玻璃卡片，自定义复选框与下拉箭头，保留明暗模式、键盘焦点与减弱透明度/动效降级。
- 修复效率中心网易企业邮箱发信后“已发送”出现两份相同邮件的问题；普通附件按 MIME 编码后的整封邮件大小做安全控制，网易大附件优先上传为云附件链接，网页会话不可用时对多页 PDF 自动分卷，识别 SMTP 直接拒收并在写信窗口显示附件上传、邮件提交进度，仍保留单次最多 10 个附件。MCP 服务管理页新增网易网页版会话 Cookie 的本机私密配置、掩码展示、清除和云附件会话验证入口。
- 增加源码版本一致性保护：私有后台和手动启动服务会监视源码变化并自动重启；运行进程与磁盘源码版本不一致时，业务接口会暂时拒绝执行；服务器状态与重启脚本会校验新进程及源码版本，避免旧后端继续提供服务。
- 修复知识库一键添加中国政府网旧版信息公开页面时正文提取失败的问题；兼容 `UCAP-CONTENT`、`pages_content`、`trs_editor_view` 等正文容器，并兼容正文位于关闭 `body/html` 标签之后的旧版页面结构。
- 重构 iPhone 主屏幕案件工作台的离线启动：应用壳改为公共且不含业务数据的精简 HTML/CSS/JS，首屏立即显示启动状态，并为 IndexedDB 增加 800ms 超时和 1.5 秒故障看门狗；Service Worker 改为经版本、类型和响应头校验的缓存优先策略，登录页不会污染壳缓存，更新失败会保留上一版本。无缓存、登录失效和存储异常均显示明确恢复入口，“修复离线应用”不会清除案件快照或待同步编辑，案件离线新增、修改、删除队列保持兼容。
- 优化应用空闲与多页面运行资源：普通源码启动不再默认开启开发热重载，未配置的旧版飞书监听器不再创建独立进程；首页连接检测由每 5 秒固定请求改为 30 秒起步的自适应退避，提醒中心只在首页可见时定时刷新，MCP 管理页随父页面隐藏暂停刷新。新增默认开启、可在性能设置关闭的智能页面休眠，首批仅覆盖统计、推荐、下载中心和使用说明等低风险只读页，高状态页面保持原行为。性能诊断现在区分当前/峰值内存并统计辅助进程、线程、异步任务和休眠页面。SQLite 统一连接策略启用可关闭的 WAL，并通过第 6 号迁移为后台到期检查增加索引；现有 API、数据字段和操作入口保持兼容。
- 优化 AI 增强的企业工商对比：能够识别问题中的多个企业主体，分别查询当前登记、历史变更及董监高/任职信息，并按企业分组保留证据后再判断交叉任职；新增企查查历史信息与董监高专项路由，避免只返回第一家企业或把未返回字段误判为“没有记录”。企业信息接口已提供历史变更和主要人员证据时不再重复调用未授权的专项服务，董监高专项仅对企业名与人员姓名双锚定的交集候选进行核验；只有每个目标企业的专项字段均实际成功返回时，才会跳过依赖补查。多企业查询改为串行限流并对临时连接失败重试，实体解析超时时按完整企业名称继续查询；人员集合只从姓名字段、法定代表人字段和明确的高管备案内容提取。
- 修复案件详情页联系人字段卡片无法通过右侧拖动手柄排序的问题；拖动后的顺序在保存案件后生效。
- 案件文件管理页及 AI 案件文件选择器现在会读取并显示 macOS 访达为文件、文件夹设置的标签颜色；带颜色的文件夹图标也会同步使用对应颜色，保留多个标签顺序，访达修改后随文件同步刷新。
- 案件文件管理页右键菜单新增访达颜色设置，可对单个或多个文件、文件夹设置或移除颜色；选择文件夹或当前目录标题时会递归同步其中全部子文件夹和文件，并立即同步到访达。
- 修复 macOS 原生壳中各页面文本框无法使用 `⌘Z` 撤销输入的问题，并补齐 `⌘⇧Z` 重做支持。
- 优化法院在线服务的浏览器运行缓存：限制普通磁盘缓存大小，关闭该专用浏览器的组件后台更新，减少 Screen AI、模型和其他 Chromium 运行组件在后台持续增长；从储存管理清理时会先关闭受控浏览器，再删除可再生成缓存，登录状态、Cookie、下载文书和案件数据保持不变。
- 业务审批表生成工具新增与文书合集一致的律师库、对方当事人库和案由库联想选择；对方当事人支持多选标签，所选案由会同步到实时预览、Word 生成和案件归档。
- 系列案件子案主表支持“Excel 导出 → 用户编辑/增删 → 导入更新”：导入确认前会展示新增、修改、删除和保持不变的逐行差异；Excel 中缺失的编号行会先移入垃圾站。每次导入前自动保存一个可回退版本，系列内最多保留最近 10 个版本，回退操作本身也会生成保护版本。
- 优化系列案件 Excel 导入确认面板：新增导入完整性检查、行数闭合与编号缺失提示；内容预览改为前 5 行的全部字段，并支持横向查看。
- 兼容旧版导入接口返回：可从原表列名推断“编号”字段；映射表统一显示中文字段名并避免英文标识和长文本溢出。未返回逐行差异时将停止确认导入，要求刷新服务后重试。
- 修复系列案件工作区偶发误显示为无样式列表的问题：按实际主表容器宽度选择桌面表格或移动卡片布局，并在嵌入窗口尺寸稳定后自动重新排版。

- 顶部标签导航与“已打开页面”总览现在将法律知识中心单独归组，计算工具、邮箱、扫描盘等页面归入“效率中心”；知识中心仍支持同时打开多个具体结论页，并以当前法律问题名称显示标签标题。

- APEX 的黑夜/白天模式现在跟随系统的 `prefers-color-scheme` 设置，并会在系统外观切换时实时同步到主页面、功能页、iframe 和离线壳。

- 知识中心「今日」与「查知识」页面的搜索框新增本地搜索历史：搜索成功后自动保存最近 10 条记录，支持按输入筛选、点击回填并立即检索、单条删除和一键清空。

- 「知识中心」已重构为面向日常使用的入口：默认「今日」聚合当前案件相关知识、最近使用与收藏；「查知识」只展示已核验结论并提供查看原文、复制引用、加入案件研究和带入 AI 的操作；新增每天 8 张的「5 分钟复习」。审核、分类合并与资料失败处理收进右上角「知识治理」，原 `/legal-knowledge` 地址和 `claim_id` 深链接保持兼容。新增第 3 号迁移及学习、复习、使用事件接口，状态失效的结论不会进入日常检索或复习。

- 「5 分钟复习」现在支持按一个或多个法律领域筛选复习卡片；未选择领域时仍复习全部领域，选择会记住并在切换时重新生成当天的 8 张卡片。

- The knowledge-base article reader now gives the main text card slightly wider
  left and right padding without changing its spacing from the outline and notes
  panels. Its smart outline now keeps repeated section labels under each major
  heading, and the highest-level outline entries use a lighter neutral style.

- The home page's tag editor was upgraded into a full “标签与分类管理” dialog
  with three segmented scopes — 全部自定义库, 专业领域, and 作者. Each scope now
  shares the Apple-inspired glass styling (frosted dialog, segmented tabs,
  editable glass rows with drag handles and count pills) and supports drag
  reordering, inline renaming, and deletion. Renaming or deleting a domain or
  author is applied to every article through new `PUT /api/domains/rename`,
  `DELETE /api/domains/{name}`, `PUT /api/authors/rename`, and
  `DELETE /api/authors/{name}` routes; ordering is remembered per scope. The
  sidebar now also honours the saved domain order.

- The global tag-and-category editor is now placed in the top-level 知识库
  header, with the empty 自定义库 state pointing back to that single entry.

- Non-editing sidebar label lists no longer show drag handles or accept
  taxonomy reordering; reordering remains available inside the tag editor.

- The AI enhance page was refined in the same Apple-inspired glass language:
  the panel now uses a translucent frosted surface with a hairline header, the
  model picker, MCP-extensions and strategy-overview controls render as glass
  pills, the history sidebar search and active items gained soft rounded
  surfaces, the suggestion cards are frosted with a hover lift, and the input
  field plus send button use a larger radius with an accent gradient. Every
  non-SVG icon in the page — MCP/Skill check marks, the scope-exit cross, close
  buttons, the folder-scope chevron and add button, file tree folder/file
  glyphs, citation link/file glyphs, source verification check, message delete
  cross, and the history group caret — was replaced with an inline SVG. The
  shortcut hint is now a borderless, muted key line, the history toggle is a
  borderless icon button that tints on hover and rotates when open, the
  file-tree chevron is a thin single-colour SVG, and the model picker’s
  provider columns each scroll independently with sticky group headings.

- The home sidebar's knowledge sections and tag list were refined in the same
  Apple-inspired glass language: section headers, nav items, tag categories and
  tags share consistent 11px-radius pills, selected rows gained a soft accent
  halo, counts render as understated glass pills, the third-level tags now show
  a hairline hierarchy guide, and the footer controls were spaced out. Every
  non-SVG icon in the sidebar — the drag handles, section chevrons, quote
  refresh, tag badge, and author glyph — was replaced with an inline SVG, and
  the drag-to-sort handles are now hidden in normal use, appearing only on
  hover, keyboard focus, or while dragging.

- The 法答网 search page was restyled in a quieter, Apple-inspired glass
  language: an ambient gradient background replaces the full-page red wash, and
  the header/search panel, topic cards, answer cards, sidebar, back-to-top
  control, and AI panel share frosted translucent surfaces, hairline borders,
  soft layered shadows, and rounded pill buttons. Every non-SVG icon — the
  update, AI, refine, restore, expand, notes, close, trash, citation, welcome,
  and status glyphs — was replaced with an inline SVG, and the sidebar section
  chevron is now an SVG data URI. Dark mode and `prefers-reduced-transparency`
  keep the same layout with legible opaque fallbacks.

- The invoice center was restyled in a quieter, Apple-inspired glass language:
  an ambient gradient background, a frosted top bar and filter strip, glass
  field/select controls with a custom APEX chevron, tinted toggles for the file
  types, a segmented tab control, and a rounded glass table card with a sticky
  blurred header and hairline row separators. The empty state now shows a
  frosted receipt badge, links render as filled gradient buttons, and the
  history, automation, preview, and toast surfaces share the same materials.
  Dark mode and `prefers-reduced-transparency` fall back to opaque surfaces for
  legibility. The invoice center's dropdowns (mailbox, quick range, and
  automation fields) now open APEX-styled menus instead of the system menu,
  the scan result no longer leaves the empty-state placeholder above the table,
  and the ZIP download link no longer shows a text underline.

- 发票中心现在可以识别百旺金穗云、广东税务数电发票等邮件正文中的参数化
  PDF/OFD/XML 下载链接，兼容税务平台的 8443 端口和无扩展名导出接口；旧版
  的失败扫描缓存会自动失效并重新尝试提取。

- 发票扫描现在有单次时间上限；无响应的外部下载链接会被跳过并显示提示，
  不会再让扫描按钮长时间停留在“扫描中”。

- All APEX default AI workflows—including Q&A, summaries, law-answer
  refinement, research memos, morning briefings, and automated filing—now call
  DeepSeek V4.1 Flash through the `deepseek-flash` gateway model. Existing
  saved V4 Flash selections are automatically migrated to the new model.

- The “一张网” inbox cards were redrawn in a quieter, Apple-inspired glass
  style: cards now use a 16px radius with hairline borders and layered soft
  shadows, delivery and signature states render as tinted pills, and the
  footer actions gained a restrained pill treatment with the primary action
  highlighted. Attachments were rebuilt as frosted liquid-glass document
  tiles with a per-extension badge (PDF keeps the brand tint), quieter
  download/archive buttons, hover lift, reduced-transparency fallback, and
  matching dark-mode surfaces.

- On mobile, a series case's “子案信息主表” now uses the same compact card
  pattern as the ordinary case list while viewing. Each card shows the child
  name, stage, number, update date, and a concise identifier; tapping it opens
  the existing full child-case detail page. “编辑主表” keeps the complete
  field-by-field table for direct editing.

### Fixed

- 知识库文章的智能目录现在可以识别带内部逗号的“一、/二、”章节标题，不再漏掉类似“二、实质合并审查趋严，明确协调审理、集中管辖的替代路径”的章节。
- 修复标签与分类管理：作者/专业领域改名保存不再因分步请求报错，标签组、标签及文章关联现在一次事务提交；同时修复删除后标签复现、未保存草稿被刷新覆盖、计数重复和离线编辑空白等问题。
- 修正待办事项列表中较长事项文本溢出标签列、遮挡提醒时间和剩余时间的问题；长文本现在会在待办列内自动换行。
- 修正移动端系列子案卡片标题字段：优先显示子案正式案件名称，纯数字子案编号仅显示在编号位置。
- Personal-center Touch ID unlock works again in the private deployment. The
  native shell's biometric challenge and session exchange now bypass the access
  login gate, matching the existing Touch ID login bridge; the exchange remains
  protected by the native-shell bridge secret.
- Switching case-management pages now leaves inactive workspaces without
  background CSS animation, while the active list removes continuous aurora and
  per-row deadline pulses. The retired sidebar pointer-glow effect has been
  removed with its related animation loop, reducing visible stutter when opening
  and changing pages.
- The case-list “全部字段” menu now remains above the sticky table header when
  open, preserving its intended parent-child menu hierarchy. The top refresh
  control now uses the supplied refresh glyph alone, with an accessible label
  retained for assistive technology.
- Opening settings through the configurable “打开设置” shortcut now lands on
  “工作空间”, consistent with the standard Settings entry. The cached client
  script revision was advanced so the new default applies immediately.
- Refreshing an open ordinary-case or series-child detail with Command-R now
  immediately restores that detail from the current-session snapshot while the
  dashboard and latest case data reload in the background. It no longer flashes
  the top-level case list for several seconds before returning to the detail.
- The series-child detail's “主表字段映射” panel now opens above the elevated
  detail drawer and shows an immediate loading state while its main-table fields
  are read, instead of appearing to do nothing.
- OpenCode Go requests and its connection check now identify APEX and provide
  the required stable session header, restoring gateway calls that had begun
  returning HTTP 400.
- Mobile (≤760px): the efficiency-center menu now opens fully on screen as a
  sheet above the bottom tab bar instead of expanding off-screen; it closes when
  tapping outside, and synthesized touch hover no longer auto-closes it.
- Mobile and light-mode sidebar: group titles are readable again; the legacy
  white text rules from the old dark sidebar now use the liquid-glass skin
  variables, so every color theme and dark mode keeps its intended contrast.
- The QQ mail page no longer overlaps its header, folder tabs, and search row
  on narrow screens; opening a mail now presents the detail as a full-screen
  overlay with a back button instead of squeezing both panes into 45vh.
- Mobile connections through Tailscale no longer flip to offline mode on a
  single stalled probe or an unreliable browser offline event: probes are
  double-checked, the home reminder center stays quiet on transient failures,
  and offline state is decided only by repeated probe failures.
- In the series main table (子案信息主表), “详情” now reliably appears above the
  full-screen series workspace instead of being hidden behind it. The action-column
  台账 button opens the same elevated child detail and preserves the child table;
  closing either view returns to that table rather than the top-level case list.

### Added

- 效率中心新增“网易企业邮箱”，复用现有邮件、发票中心和自动归集能力；网易邮箱通过 IMAP/SMTP 客户端授权码接入。

- 效率中心新增“快速报批”，复用明思登录状态，支持多种文书类型上传并提交用章申请。
- Shortcut action choices now derive from every independently openable page
  type. Current work, case, document, communication, and management tools are
  included; future page types are added automatically unless they require a
  specific case, article, or external-link context.
- Series-main-table columns mapped to “联系与备忘” now appear as contacts in
  the “联调/诉讼/仲裁阶段” group rather than creating their own group. In the
  edit view, contact entries in ordinary cases and series children can now be
  dragged between any contact groups and saved in their destination group.
- Series-child “详情” now opens the same full case-detail page used by ordinary
  cases. Its “主表字段映射” workspace lets users select a child-table column and
  a destination detail field without native menus or dialogs; mappings apply to
  every child in that series, persist across sessions, and refresh the open
  detail page immediately. Supported destinations include “其他当事人”, a named
  contact-and-memo card, case memo, case type, stage, case number, and court.
- Storage management now separates regenerable court-service Chromium caches
  from backend code; clearing them preserves sign-in state, preferences,
  downloaded documents, and case data.
- Added the selectable “历史备份文件” category. Existing migration snapshots and
  every future migration-created snapshot are grouped there for manual cleanup.

- Hearing-detail drawer now shows the linked case's "联系与备忘" hub instead of
  the legacy 联系方式 fields. For a series child it lists every cell in the
  child's main table that the contact-recognition rule flags (phone or email),
  each with its iCloud 通讯录 sync button; the drawer keeps the legacy fields
  only as a fallback when the case cannot be loaded. The calendar's 开庭详情
  popup gets the same treatment, and the calendar's series hearing-group popup
  appends each child's recognized contacts under its own entry; 待办/保全/上诉
  popups keep the legacy fields.
- An isolated APEX Mobile anonymous-pilot container, fictional starter records,
  and phone-install metadata. It cannot start with normal database filenames or
  external service credentials.
- Repository governance for continuous AI-assisted development, including shared
  capability tracking, API contract checks, visual rules, and performance budgets.
- A shared client picker and client-data adapter across six case and document pages.
- A local performance panel for page counts, iframe counts, long tasks, Python
  memory, slow requests, and API P95 latency.
- Numbered, repeat-safe database migrations with automatic pre-migration backups.
- Automatic recovery when the macOS WebKit content process terminates.
- Anonymous light and dark visual baselines for shared controls.
- The shared client picker now offers a complete, browsable client list with
  incremental paging and visible counters, three predictable sort modes
  (frequent, name, recently updated) with sticky initial-character grouping,
  recent-client shortcuts, match highlighting, a first-character badge, refined
  check/tick indicators, keyboard paging keys, and bottom-aware menu placement.
- The case-detail "客户信息" table now uses the shared client picker instead of
  a separate 12-result lookup, so selecting a client there gets the same
  complete list, sorting, recents, and highlighting as the document pages.
- In series main-table edit mode, holding Command (or Ctrl) and clicking now
  selects multiple non-contiguous cells, and Command+C copies every selected
  cell (contiguous or not) as a tab/newline grid. Selected cells are counted in
  the sheet status bar, and a non-rectangular selection anchors paste at its
  first cell.

### Changed

- 知识中心支持同时打开多个具体结论页面，并按页面实际法律问题名称显示在顶部标签下拉菜单和已打开页面全览卡片中。
- 顶部标签导航和“已打开页面”全览中的知识中心分类统一显示为“知识中心”。
- “我的笔记”导航计数现在显示笔记条数，而不是有笔记的文章数量。
- Settings now opens on “工作空间” by default, and that category appears first
  in the left-hand list.
- The “系统与支持” diagnostics area now presents compact performance cards,
  a unified status-and-refresh row, and a bounded slow-request list with
  readable paths and durations.
- Settings now uses a restrained three-level structure: category, page, and
  functional section. Redundant navigation subtitles and generic colored
  labels were removed; section titles now state the actual setting scope.
- Client picker menus across all case and document pages adopt the shared
  design tokens for surfaces, motion, and focus states in light and dark mode.
- Client picker menus are now anchored to the viewport (fixed positioning with
  a body portal, like the shared date picker) instead of living inside scrollable
  drawers and forms. They can no longer be clipped by container boundaries, they
  flip above the input when space below is tight, and scrolling the page no
  longer fights with scrolling the list.

## Versioning

Stable local releases use tags in the form `apex-YYYY.MM.DD.N`. Database migrations
have independent monotonically increasing identifiers and are never inferred from
the application version.

- Theme colors now follow the selected palette across the knowledge center, AI API settings, calculator, court directory, file and archive pages, and shared controls. Brand accents remain separate from danger and status colors.

## 2026-10-09：直接问 AI 与通用联网搜索

- AI 增强新增“直接问 AI”和“直接问 AI · 联网搜索”，独立保存对话，不再强制检索知识库或 MCP。联网模式复用公开网页检索能力供所有模型回答，并返回实际网页来源。
- 加入豆包 Seed 2.1 Pro / Lite 0915 API 型号（当前账户需开通）；Mini 切换至实测可用的 260428 版本，保留已有 Pro / Lite 接口。

## 2026-10-09：联网检索质量修复

- 联网问答先转换口语查询，结合当前日期与续问对象生成多个搜索词，并过滤不相关的网页。无需外部资料的创作和模型身份问题跳过检索。
- 公开网页检索增加备用搜索入口，修复请求头、压缩响应和网页跳转兼容问题，优先采用指定官方来源，标明检索时间并限制等待时间。直接 AI 与文件问答复用同一检索实现。

## 2026-10-10

- 效率中心在 AI增强下方新增“案件 AI 管理”，复用模型选择、问答、历史、复制与导出。
- 案件问答查询全部在办/归档案件及关联详情，支持跨案件统计与细节追问；涵盖一张网已同步案件、立案审核、开庭、送达、消息和附件记录，并展示查询依据。
- 案件问答范围及历史独立于普通 AI增强；只读查询不修改案件资料，同步记录不冒充官网实时状态。
- 案件问答移除文件和 Skill 入口，优化表格及历史列表；依据显示中文摘要并可打开具体案件详情，兼容旧回答的原始数据展示。

- 2026-10-14：事实核对与证据册第二轮修复：固定材料副本与解析底稿，保留PDF可见批注/表单，避免新任务覆盖未保存复核；工作台升级简洁磨砂玻璃导航及明暗阅读界面。

- 2026-10-14：升级文书事实核对与证据编排：以定稿文书为编排依据，保留文书事项和人工复核；自动拟定带原文出处的证据摘要/证明内容，支持多材料、分组、选页、合并拆分及草稿版本；同步证据目录、连续页码、原件映射与内部文书对应表。

- 2026-10-14：证据工作台再次审查修复旧任务续办、预览校验和任务登记竞态；拆分后重新确认摘要与文书关联。编排界面精简为磨砂目录导航、单项编辑和同步原文预览，输入区可折叠。

## 2026-10-14 AI 生成文件

- 直接问 AI 可交付 HTML、SVG、CSV、JSON、TXT、Markdown 文件；文本文件可转为 Word。
- 图形及 HTML 显示隔离预览和下载卡片，无需手动复制代码保存；历史完整代码块也可直接下载。
- 保留原有整条回答导出和统一下载中心记录。

- 2026-10-19：储存管理的导出文件展示完整可搜索明细、路径、用途、修改时间和下载入口，支持下载完整清单及勾选确认清理；修正将公开版打包与验收产物笼统归为系统业务导出的说明。

### 2026-10-19 下载中心审查与清理

- 补齐案件、归档、知识库、计算工具、扫描件、费用、立案等导出来源，统一登记直接下载入口。
- 新增全局文件大小排序、大小范围及下载／生成日期筛选，显示真实大小与文件状态。
- 新增缺失文件分析和复核后的批量记录清理；勾选现有文件后可确认移到废纸篓。
- 修复筛选请求丢失、浏览器历史超过 200 条时漏导入及系统取消保存误标失败。

### 2026-10-19 下载中心界面与操作文案

- 采用分组侧栏、磨砂搜索栏和紧凑文件列表；大小与日期筛选按需展开，选中文件后显示批量操作。
- 文件大小与时间分列，任务汇总使用独立图标，完整路径通过悬停查看；适配浅色、深色和窄屏。
- 用具体页面名称替换“返回来源”等模糊入口，明确区分“移除记录”和“移到废纸篓”；同步确认按钮及历史错误提示。

## 2026-10-19 · 公开版更新与应用统计

- 公开版接入 Sparkle 2.10，最低 macOS 12；支持检查更新、签名增量更新及完整包回退。
- 更新前正常结束本地服务，版本变化时备份数据库，保留独立目录中的案件和文件。
- 增加管理员登录保护的应用统计后台，分别展示安装包请求次数、同意统计的首次启动设备和近期活跃设备。
- 匿名统计须用户同意，可随时关闭，不上传案件、文件、邮箱或问答内容。

## 2026-10-20 · 后台连接修复

- 管理后台增加无需绑卡的 Pages 入口，复用原有账号密码和统计数据，避免客户端直接连接不可达的 workers.dev 域名。
- 修复登录页空白、登录后首页 404 和静态资源错误被显示为成功的问题。
