# Public macOS updates and application statistics

## Boundaries

Public builds require macOS 12 and use Sparkle 2.10.0, pinned to the upstream
SHA-256 in `scripts/distribution/sparkle_tools.py`. The private development app
keeps its existing identity, port and launch behavior. No installed-public-user
transition is supported or required for this first updater-enabled release.

The public identity is `com.stella.public.native`, loopback port 18865. The native
executable owns the packaged Python process. Startup waits for a PID-specific
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
     --metrics-url https://stella-public-admin.cuplsilence.workers.dev/v1/events
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

Production endpoint: https://stella-public-admin.cuplsilence.workers.dev
The default workers.dev hostname must be reachable from client networks; a
successful deployment does not establish connectivity from mainland networks.
Test it from target users' networks before publishing an installer. If blocked,
configure a reachable publisher-owned custom domain and use it in new app builds.

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
