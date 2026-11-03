# 官网互动统计与后台呈现（2026-10-31）

恢复点：应用仓库 `legal-kb` 的 `7ebef81`（分支
`模型服务/stella-settings-refresh-20261030`，开始时已有与本任务无关的未提交改动，
本次只改 `services/public-admin` 与统计文档）；官网仓库 `stella-downloads`
的 `fee0a6e`（main，开始时干净）。后台已部署到生产并完成不写入测试数据的上线检查；
官网采集脚本改动已准备但尚未提交/推送。未发布任何安装包。

## 对齐的官网交互

以当前已发布的 `https://liu-zongjin.github.io/stella-downloads/` 为准：

- 首页、下载指引与新增介绍视频页 `watch.html` 的访问落点。
- 下载页 AI 源码安装区 `#agent-install`、视频播放区、按功能观看章节。
- 复制 Mac / Windows 源码安装指令。
- 切换 Apple 芯片 / Intel / Windows 安装标签。
- 点击所列 AI 助手官网入口。
- 既有下载点击与夸克 / GitHub 渠道保持不变。

## 变更

- 新增独立增量表 `website_interactions`（`0005_website_interactions.sql`），
  不修改 `website_events` 和历史事件。
- `src/website.js` 扩展区块白名单（`watch`、`agent-install`、`film`、
  `chapters`）和互动事件校验：`copy`、`tab`、`video`、`chapter`、`assistant`，
  页面与明细均按白名单校验。
- `/api/website` 增加互动汇总与四个分布维度，沿用原有日期 / 设备筛选；
  90 天清理同时覆盖新表。
- 后台新增第二组指标卡、四块互动面板、每日互动列、固定零值行、空状态、CSV 互动汇总与维度；
  章节编号映射为官网公开章节标题，未知编号显示“章节 NN”。
- 官网新增 `docs/analytics-20261031.js`；首页、下载页切换到新脚本，
  视频页首次接入采集脚本与统计退出按钮；`watch.css` 页脚允许换行。
- 采集仍遵循 DNT / GPC、退出偏好、隐藏页面停发；互动载荷只含控件类别与公开编号。

## 验证

- `services/public-admin`：23 项测试全部通过（含新增区块、互动白名单、
  去重、筛选、CSV 相关渲染）。
- `stella-downloads`：10 项采集脚本测试全部通过（含视频、章节、复制、标签、
  页内系统跳转、AI 助手、退出与隐藏页面）。
- 本地 Miniflare D1 应用 0005 迁移后导入匿名夹具：48 条访问事件、18 条互动；
  再用公开采集接口写入 1 条视频页访问和 3 条互动事件，后台汇总、分布和筛选均正确。
- 浏览器检查（WebKit，本地测试凭据，未写入生产）：1440×900 浅色 / 深色、
  1024×768、390×844；无脚本或控制台错误（全页截图时 WebKit 的截图样式提示除外），
  页面无横向溢出；“官网访问 / 应用统计 / 系统消息”三个标签可切换；
  设备与日期筛选生效；CSV 含互动汇总和维度。
- 真实浏览器验证新采集脚本：在本地静态站点上点击复制、系统标签、AI 助手入口、
  视频播放与章节，事件字段和值均符合白名单；视频页、下载页页脚统计按钮布局正常，
  页面无横向溢出。
- 顺带为下载页补充统计样式表与按钮 class，使原有统计退出按钮与其他页面一致。
- 截图与本地导出 CSV：`outputs/stella-admin-interactions-20261031/`。
  夹具仅用于本地 D1 和本地后台，未向生产写入测试事件或测试消息。

## 生产部署（2026-10-31 / 11-01，已执行 1–5）

1. 生产 D1 备份导出到 owner-only、被忽略的
   `legal-kb/services/public-admin/.tmp/stella-public-metrics-20261031.sql`；
   在内存 SQLite 中恢复并通过 `integrity_check`，导出前 820 条访问事件、
   4 条系统消息、1 条安装记录，尚无互动表。
2. 远程 D1 应用 `0005_website_interactions.sql` 成功，仅新增互动表和索引。
3. Worker 部署成功，版本 `62d6d644-fc02-4b20-800f-6a2edcfe57ce`；上传了 2 个变更静态资源
   （`index.html`、`website-admin.js`）。`stella-admin.pages.dev` 的 Service Binding
   继续指向该 Worker，Pages 入口无需改动。
4. 官网采集脚本已发布：提交 `2ac6781` 将 `analytics-20261031.js` 接入首页、下载页和
   视频页，GitHub Pages 已生效；`download.html` 同时补齐统计样式表和按钮 class。
   2026-11-01 生产 D1 已收到新的 `video` 互动记录（1 条），说明新采集链路已打通；
   复制、标签、章节、AI 助手等事件会随真实点击逐步出现在后台。
5. 生产不写入测试事件：使用管理员会话验证
   - `/` 未登录返回 303 到 `/login`，登录页 200；
   - 登录 200，`/api/website?days=30&device=all` 返回 200 且包含
     `copies`、`tabs`、`video_plays`、`chapter_seeks`、`assistant_clicks`、
     四个 `*_targets` 和 `interaction_trend`；现有 30 天数据正常（181 PV、44 访客、30 次下载点击）；
   - `/api/summary`、`/api/messages` 仍为 200；
   - `/website-admin.js` 与 `/` 的静态资源已更新，包含新卡片、四个互动面板和趋势“互动”列；
   - WebKit 登录后检查：无脚本错误、无横向溢出、互动面板各显示 8 / 5 个零值行；
     由于没有新脚本事件，互动指标为 0 属预期。
6. 若需回滚：恢复官网旧脚本即停止新采集；后台表为增量，可保留或单独删除。
   部署前的 D1 备份可用于恢复数据库。

Cloudflare OAuth 在本机沙箱内不能写入默认的
`~/Library/Preferences/.wrangler`，本次将 Wrangler 配置放在被忽略的
`.tmp/wrangler-home`（owner-only）；后续部署可继续复用，令牌失效后重新
`wrangler login` 即可。


## 首页 hero 下载操作区二次优化（2026-11-01）

用户反馈第一版分组卡片与官网其他元素融合感不足（m00883），要求继续优化。
调整原则是不再新增“卡片”，而是复用官网已有的排版语言：

- 移除 `.hero-actions` 的边框、圆角、浅色底和阴影，不再形成独立卡片；
- “复制指令，让 AI 帮你安装”由描边按钮改为红色文字链接，与官网其他
  `.text-link` / 红色链接保持同一层级；
- “推荐 … · 版本 · 要求”放在主按钮之后，作为紧邻按钮的说明文字；
- 说明文字、AI 链接和页脚链接统一内缩 18px，与主按钮文字左对齐；
- 只用一条 1px 分隔线收住“观看介绍片 / GitHub 发布与校验”两个弱链接，
  分隔线横跨整个操作列，文字仍与按钮文字对齐；
- 桌面端操作列仍与主标题右缘大致对齐；≤900px 时整块落到简介下方，
  宽度不超过 420px；≤720px 时占满内容宽度，页脚链接可换行。

提交：`b1d865d`（移除卡片、AI 改文字链接）、`69614e2`（文案与按钮文字对齐）。
线上核验（https://liu-zongjin.github.io/stella-downloads/，WebKit）：
1386×756 与 390×844 均无横向溢出、无脚本错误；`.hero-actions` 计算样式
`border: 0`、背景透明；截图见 `outputs/stella-admin-interactions-20261031/`
下的 `live-hero-integrated-1386.png` 与 `live-hero-integrated-mobile-page.png`。
