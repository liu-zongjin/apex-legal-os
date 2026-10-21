# Public macOS updates and application statistics

## 固定发布规则（用户于 2026-10-20 明确确认）

所有迭代、优化、修复和测试默认在本地 Stella 的同一套项目源码中进行，
并在本地生效供用户测试；不长期维护另一套公开版功能源码。
只有用户在本地测试后明确指令“打包并在官网发布最新公开版”时，才制作、
上传或替换公开安装包、增量更新及更新订阅。提交或合并 GitHub 源码、更新
官网功能记录均不等于发布安装包的授权。本次设定规则也不触发打包或发布。
官网为 https://liu-zongjin.github.io/stella-downloads/ 。

获准发布时，以当时已完成本地测试的最新本地版本为准，核对并提交全部预期
变更后冻结该提交，记录源码提交号和版本号；不能使用过期分支，也不能因为
打包工具只读取 Git HEAD 而遗漏已测试但尚未提交的修改。

公开包和更新包不得包含作者本地用户数据，包括一张网预置手机号及账号、
团队律师、客户、对方当事人、案件、联系人、附件、生成文书、数据库、
浏览器登录状态及存储、密钥、令牌和个人配置。还应检查源码及资源中硬编码的
真实默认值、示例和预置资料；只排除数据库并不足够。新用户使用空白初始化
或经确认的虚构示例。应用功能和文书排版仍复用本地实现。

打包在隔离目录进行，不清空或改动作者本地运行数据。发布前检查最终产物的
隐私安全，并使用临时匿名资料验证首次启动、升级及数据保留。增量包只能由
上次实际发布的脱敏完整包与本次脱敏完整包生成，不比较或上传本地运行数据；
升级保留接收用户自己的本地数据和配置，无合适增量时提供完整包更新。

## Boundaries

Public builds require macOS 12 and use Sparkle 2.10.0, pinned to the upstream
SHA-256 in `scripts/distribution/sparkle_tools.py`. The private development app
keeps its existing identity, port and launch behavior. No installed-public-user
transition is supported or required for this first updater-enabled release.

The public identity is `com.stella.public.native`, loopback port 18865. The native
executable owns the packaged Python process. Startup waits for a launch-specific random
marker written after Uvicorn binds successfully. An exclusive runtime lock covers
backup, migration and serving. Quit/update waits up to 30 seconds for normal backend
shutdown; if it has not exited, termination is cancelled rather than killing an
in-progress write. SQLite is backed up with its online backup API before importing
new backend code on an application build change. Numbered migrations retain their
existing backup protocol too. Backups and all cases, attachments, configuration,
WebKit data and preferences stay outside the replaceable application bundle.

`~/Library/Application Support/StellaPublic` is never copied into an update ZIP.
Restoring an earlier binary does not automatically downgrade a migrated database;
recovery requires a compatible binary plus its pre-update database backup. Do not
restore a database while the app/backend is running. User files are not rolled back.

## Build and publish

1. Commit reviewed program sources: the builder deliberately freezes Git HEAD,
   never uncommitted files or the live runtime.
2. Generate the release signing key once with the verified SDK:
   `.tmp/sparkle-2.10.0/bin/generate_keys --account stella-public`.
   The private key remains in the login Keychain. Back it up securely using the
   upstream key transfer process; never commit it or put it on GitHub Pages.
3. Build into a new directory (never the running `dist/Stella.app`):

   ```sh
   python3 scripts/build_private_preview.py --output /absolute/new/output \
     --version 1.0.1 --build 2026101901 \
     --metrics-url https://stella-admin.pages.dev/v1/events
   ```

   Build numbers are positive monotonically increasing integers. A release build
   number and its archive bytes must never be reused. Licenses reside inside the
   app; the ZIP contains only Stella.app. The SDK is fetched from official GitHub,
   checksum verified and its symlinks preserved. The current local toolchain has
   an older SDK; missing Swift annotation macros are filled only at compile time.
   No upstream framework headers or runtime code are changed.
4. Keep all exact previously published update ZIPs in an ignored archive folder.
   Place the new ZIP there and prepare the next release:

   ```sh
   python3 scripts/distribution/prepare_update.py --archives /absolute/archives \
     --newest /absolute/archives/Stella-macOS-AppleSilicon-v1.0.1-2026101901.zip \
     --notes /absolute/release-notes.md
   ```

   Sparkle generates and signs the feed, full archive enclosures and eligible
   deltas. The script checks identity, minimum OS, unique/increasing build numbers,
   public signing key, byte lengths, signatures and exact GitHub download URLs.
   Inspect `release-plan.json`. Keep the feed between runs: older release URLs
   must retain their original tags. Do not modify immutable published assets.
5. Upload the plan's full ZIP and delta assets to its public GitHub Release tag;
   verify their HTTPS URLs and checksums before copying appcast.xml to the public
   website repository's `docs/`. Update website links/requirements/normal feature
   notes when actually publishing the new package. Never publish private source.
6. On a disposable user profile, test the older app's check/update/relaunch with
   fixture data, and separately verify full-archive fallback with no eligible delta.
   A first release has no earlier updater-enabled archive, so cannot have a delta.

Sparkle handles update checks and native update prompts. Automatic downloading /
installation is disabled; checking is enabled. The app menu also offers manual
“检查更新…”. Sparkle's built-in optional system profiling is disabled. Updates
are Ed25519 signed and verified before extraction; code signing is currently
ad hoc, consistent with existing distribution. Developer ID signing/notarization
is not claimed; those require the publisher's Apple Developer credentials.

## Workers + D1 administration (no Access subscription)

Cloudflare account authentication is required for deployment, but Cloudflare
Access / Zero Trust is **not used**. No card is required by this deployment's
Workers + D1 free-plan flow. Do not activate the separate Zero Trust checkout.
Do not silently upgrade to a paid plan; quota exhaustion must fail explicitly.

Project: `services/public-admin`. Install with `npm ci`, run `npm test` and
`npx wrangler deploy --dry-run` in that directory. Apply D1 migrations before
`npx wrangler deploy`. The remote database is separate from every app's local
case database. Wrangler account credentials remain in its own local config.

Production entrance: https://stella-admin.pages.dev
Telemetry endpoint: https://stella-admin.pages.dev/v1/events

`services/public-admin-entrance` is a small Pages Function bound to the existing
Worker through `ADMIN`. It forwards the original Request directly through the
private Service Binding, preserving origin, body, cookies and responses. It does
not resolve or redirect the client to the unreachable workers.dev hostname. The
Worker remains the only implementation of auth, static assets, D1 access, rate
limiting and scheduled synchronization. The entrance contains no credentials and
no copy of private dashboard data. Failures return an explicit no-store 503.

Deploy from `services/public-admin-entrance` with:

```sh
../public-admin/node_modules/.bin/wrangler pages deploy --branch main
```

The project was created directly on the existing Pages platform. For an already
created project, do not pass `--force` or delegate creation to a new Workers site.
The Pages config remains separate from the Worker's config. All routes, including
static files, pass through the bound Worker's authentication policy. Static fallback
contains only a generic unavailable message. Worker assets set `html_handling` to
`none`; explicit `/login.html` and `/index.html` resolution avoids automatic clean-URL
redirects becoming blank 200 responses. Upstream status codes are preserved.

The old `https://stella-public-admin.cuplsilence.workers.dev` hostname remains a
compatible direct entrance where reachable. It is not the address to give users
or put into new package builds. Earlier ignored candidate bundles using that old
metrics URL are test artifacts and must be rebuilt with the new telemetry URL
before release. No existing public installer was changed in this connectivity fix.

Current-network live checks passed for the new entrance. As with any third-party
hostname, this does not guarantee every network or permanent availability. A future
publisher-owned domain can be added when available without replacing D1 or auth.

Administrator authentication uses an independently generated 256-bit password,
not an application-embedded API key. Only its SHA-256 digest is stored as Worker
secret `ADMIN_PASSWORD_SHA256`. `ADMIN_SESSION_SECRET` is a separate random secret.
The high-entropy generated password is essential: do not replace this scheme with
a weak user-chosen password without adding an appropriate password KDF.
A successful login issues an eight-hour HMAC-signed, Secure/HttpOnly/SameSite=Strict
host-only cookie. Login is rate limited, requires same-origin POST and bounded
JSON; logout is same-origin POST too. All dashboard APIs and content require a
valid session, including workers.dev/preview routes. Only the login screen and
its non-sensitive styles/script are public. Content is no-store with a restrictive
CSP. Rotating the session secret invalidates all sessions. Rotating the password
alone does not revoke existing sessions; rotate both after exposure.

Local initial password: `~/.config/stella-admin/credentials.txt` (owner-only file).
Never paste it into a public issue, repository, installer or telemetry payload.
Reset by generating a new random password and rotating both Worker secrets through
Wrangler; keep cleartext only in a password manager or owner-only local file.

## Telemetry contract and honest metrics

On first successful launch, the public app asks permission for anonymous statistics.
The app menu “匿名使用统计…” allows changing that choice. Refusal sends nothing.
Accepted payloads contain **only** a random UUIDv4 installation ID, numeric app
build and macOS version. They are submitted over HTTPS every 60 seconds while
running, without cookies, credentials or persistent retry queue. No cases,
filenames, mail, real account identifiers, questions or answers are sent.

The public POST `/v1/events` is size bounded and rate limited. Server timestamps
are authoritative. D1 stores only the installation ID's namespaced SHA-256 hash,
first/last seen time, build, OS version and daily activity. Daily records expire
at 90 days; lifetime installation summaries persist. Cloudflare infrastructure
necessarily sees requests/IPs and may maintain its own security records; the app's
D1 tables and Worker application logging do not retain IP addresses. Rate limiting
uses an ephemeral IP key. The endpoint is public: spoofed installations cannot be
fully prevented without a trusted enrollment system. Counts are operational estimates.

- Downloads: current GitHub full ZIP/DMG release asset counters; include repeated
  requests and full-package update requests. They are not unique users or proof of
  completed file transfers. Delta/help-file requests are excluded. Snapshot sync
  is every ten minutes. Failures keep the previous snapshot and show stale status.
- First launches: unique reporting installation IDs that reached backend readiness
  and allowed statistics. Not a count of drag-to-Applications actions or people.
- Running: IDs seen in the last five minutes, which may include background apps.
- 30-day active: distinct IDs seen in the last thirty days. Offline/opted-out users
  are absent; resetting preferences can produce a new ID. Daily UTC trend records
  are independently deduplicated.

The dashboard refreshes every thirty seconds while visible and stops hidden-page
requests. It displays empty/error states rather than inventing zero download counts
when GitHub has never synchronized. Test data must stay in local Miniflare D1.

## Public system messages

The dashboard's “系统消息” panel lets an administrator enter a title (80 characters)
and body (6000 characters), preview the exact plain text, and explicitly confirm
publication to all supported public apps. HTML/Markdown/links are not interpreted.
Published content is immutable; withdraw and publish a new message to correct it.
The confirmation sheet explains withdrawal. Admin history uses 50-row pages;
no more than 100 announcements can remain active concurrently. All content is
public: do not publish case details, credentials or personal data. Do not publish
test announcements into production; use Miniflare fixtures.

- `GET /api/messages?offset=0`: authenticated history, `{messages, has_more}`.
- `POST /api/messages`: authenticated same-origin bounded JSON `{title, body}`;
  returns immutable UUID, title/body and Unix `published_at`; 409 at active limit.
- `POST /api/messages/{id}/withdraw`: authenticated same-origin idempotent withdrawal.
- `GET /v1/messages`: public CORS feed `{messages: [{id,title,body,published_at}]}`,
  newest first, max 100, no-store; no login, cookies or installation identifier.

Apply `0002_messages.sql` after exporting a D1 backup to an owner-only ignored
local file, then deploy the Worker. Pages automatically forwards the new routes
through its existing private Service Binding. It needs no redeployment or new
secrets. The existing installations/download tables are not modified.

The canonical homepage used by local, public and PWA editions includes the same
versioned message assets and `https://stella-admin.pages.dev/v1/messages` meta tag.
No public-only UI injection is required. Use the current
`https://stella-admin.pages.dev/v1/events` metrics URL when building.

The toolbar bell opens a styled, keyboard-accessible message panel. Opening the
message panel marks the current list read only on that device; messages fetched
while it remains open are also considered read. Bounded localStorage keys
`stella.system-messages.v1` and `stella.system-messages.read.v1` store only public
message text and read IDs. They do not touch case files or app databases. Fetches
occur at startup, foreground return, network reconnect, panel opening and every
five minutes while visible; hidden pages abort requests and stop timers. Ten-second
request and 2.6 MB response limits bound failure handling. Offline/failure preserves
last-known content with an explicit sync-status label; successful synchronization
replaces the entire active set, removing withdrawals. No delivery/read receipts
are collected, and the backend cannot claim that every device has received a
message. Statistics opt-out does not disable system messages.

This is foreground polling rather than APNs/background push. A closed or offline
app receives current active messages the next time it starts/connects. Installers
without this code cannot gain a message button remotely; release a new package
before expecting users to receive messages. This source/deployment change does
not itself publish or replace an installer. Test actual packaged WebKit/network
behavior in the next public-release workflow.


## Unified local/public personalization and API setup

The local app is the source UI for future public builds. `GET/PUT /api/appearance`
uses the existing `app_preferences` table under key `stella.appearance.v1`;
new runtimes default to “新用户” and blank firm identity/logo. Existing configured
profiles are not reset. Settings → 外观与体验 edits the greeting name, firm name,
firm logo, document abbreviation and optional firm contact details. The application
brand logo remains a separate setting. Sidebar greeting defaults hidden unless the
user has opted to show it. The same name updates ordinary and case-context AI
welcomes without clearing chat history. Form drafts survive foreground refresh.

Only PNG/WebP logos up to 1.5 MB / 4096 pixels are accepted and re-encoded as PNG.
Browser previews and all standalone/bundle/case-save DOCX paths use the same profile
without changing existing page/table typography and geometry. Missing firm identity
leaves those fields empty and shows a settings shortcut inside the form column.
No installation copies Stella branding into the law-firm logo slot. A document
abbreviation entered with a trailing “函字第”/“律字第” is normalized to avoid repetition.

Meeting-room and quick-approval entries display the same customization notice in
all editions, then allow explicit `?experience=1` navigation to the original tool.
“知悉以上情况，不再提示” persists only a shared per-browser acknowledgment. No vendor
credentials are fabricated and the actual tools still require corresponding access.

AI API management exposes independent `judicial_messages` and `hearing_notice`
purpose models. SMS's existing settings UI mirrors the central purpose preference.
Custom API setup supports Chat Completions and Responses, with OpenAI/ChatGPT and
Kimi address/protocol presets; model IDs are user-entered rather than guessed from
an account's entitlements. Custom providers get stable `custom_*` IDs and appear in
AI enhancement and all purpose selectors. The existing request/streaming adapters
are shared. Responses requests replay local history with `store:false`.

Custom configuration including keys stays in owner-only ignored
`local_ai_custom_providers.json` under the runtime config directory. API responses
return masked keys only. New writes require the app origin, endpoint URLs must be
HTTPS without userinfo/query secrets, and redirects are not followed with keys.
Removing providers/models resets invalid saved selections; unknown custom IDs
cannot accidentally route to another provider. Deleting a provider does not delete
AI chats, memories or case records.

Official transport references checked during implementation:
- https://developers.openai.com/api/docs/quickstart
- https://platform.kimi.com/docs/api/chat

The Cloudflare announcement UI/feed was deployed after an owner-only D1 export
and additive `0002_messages.sql`. No production test message was published and no
public installer was replaced. Main-source/native visual verification is separate
from a future complete Sparkle GUI install/update validation.

## Intel Mac packaging

Intel and Apple Silicon packages use the same source and `StellaPublic` data format, but require different binaries. Run `scripts/build_private_preview.py --arch x86_64` under an x86_64 Mac Python with isolated x86_64 dependencies (on Apple Silicon, `arch -x86_64 /path/to/intel-venv/bin/python`). The builder uses that exact interpreter, passes the PyInstaller target architecture, builds both Swift executables for that target, and checks every nested Mach-O before signing. Do not reuse the Apple Silicon site's compiled dependencies.

Intel archives use `Stella-macOS-Intel-...zip`, metadata `StellaArchitecture=x86_64` and `/appcast-intel.xml`; Apple Silicon retains `/appcast.xml`. Keep architecture archives in separate directories when preparing feeds/deltas. Older packages without architecture metadata are the existing Apple Silicon family. This prevents an Intel installation from accepting an arm64-only update. Feed generation and publication still require their existing explicit release authorization; creating a local Intel installer does not publish the Intel update channel.


## 官网访问统计与后台导航（2026-10-21）

后台使用 `#website` / `#application` / `#messages` 三个导航标签；首次进入默认官网访问。
未选中的标签不定时请求数据。官网 `analytics-20261021.js` 向独立的
`POST /v1/website-events` 发送 pageview / section / download 事件，既有应用
`/v1/events` 与系统消息接口保持兼容。网站统计不依赖应用内的匿名统计开关。

官网统计不使用 Cookie 或指纹。localStorage 保存随机访客 UUID 和退出偏好，
sessionStorage 保存标签页会话 UUID（闲置 30 分钟后新建）；服务端只保存访客与会话
的命名空间 SHA-256 哈希。存储不可用时仅在当前页面内去重，关闭统计即停止采集并删除
本地标识；遵循 DNT / GPC。只上报事件 ID、随机访客/会话 ID、允许的区块/下载平台和
来源域名；不会上报完整 URL、查询参数或页面内容。Worker 根据请求归类设备、系统、
浏览器与 Cloudflare 国家/地区代码，不保存 IP 或原始 User-Agent。公开接口存在伪造、
拦截、网络失败和浏览器去重偏差，不能据此认定真实人数或下载完成。

`GET /api/website?days=30&device=all` 需要原有管理员会话。days 支持 1/7/30/90，
device 支持 all/desktop/mobile/tablet。以北京时间自然日为界，提供 PV、去重访客、
会话、下载点击及点击访客、每日趋势、小时分布、来源/国家/地区/设备/系统/浏览器、
区块浏览、入口锚点及下载版本分布（各维度最多 20 行）。访客/会话计数包含范围内的
区块和点击事件；各维度中的来源/设备等按 PV 汇总，区块和下载分别按自身事件汇总。
后台支持导出当前范围的 CSV。采集从首次成功事件起算，不能恢复历史数据。

新增独立限流绑定 WEBSITE_LIMITER（每 IP 每分钟 60 次，仅瞬时使用 IP）；
仅允许 `https://liu-zongjin.github.io` 来源，严格校验字段、2048 字节上限、
UUID 事件幂等，忽略已知爬虫。CORS 并非可信设备认证。定时清理保留今天及之前 89 个
北京时间自然日；首次采集时间独立保留。上线前导出 D1 备份再应用 `0003_website.sql`，
部署 Worker 后更新官网静态脚本；Pages Service Binding 无须修改。回滚官网脚本可停止
新采集；数据库为增量表，回滚 Worker 时保留表即可。此操作不更换任何安装包或更新源。
