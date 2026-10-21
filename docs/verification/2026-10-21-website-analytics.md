# Website analytics and multi-navigation administration

Canonical source base / recovery point: `4768d40`.
Source branch: `codex/admin-website-analytics-20261021` (kept separate from main).
Website base / recovery point: `6c143e8` in stella-downloads.

## Completed verification

- `python3 scripts/apex_guard.py preflight`: passed.
- `python3 scripts/apex_guard.py extended`: passed, 1031 tests, 13 existing skips.
- Public-admin `npm test`: 15 passed, including real temporary D1 ingestion,
  event idempotence, visitor/session deduplication, allowed origin and fields,
  body size, privacy headers, rate limiting, crawler filtering, device filters,
  90-day query boundary, Shanghai midnight, existing login/messages/entrance.
- Website `node --test tests/analytics.test.cjs`: 5 passed, covering deep-link
  pageviews, host-only referrer, download platform, DNT, opt-out identifier reset,
  blocked storage and hidden-page suppression.
- Wrangler deployment dry-run passed; existing D1/auth/service binding retained,
  independent WEBSITE_LIMITER added.
- Browser checked all three navigation entries, range selection, existing app
  metrics, empty message history, opening/closing the message editor, and final
  website statistics layout using **local anonymous example data only**.
- Historical days before started_at show “未采集”, rather than invented zeros.
- No production test messages or synthetic analytics events are sent.

## Deployment

Before applying migration 0003, export D1 to an ignored owner-only file under
`.tmp/admin-analytics-20261021/`; validate by restoring into in-memory SQLite.
Wrangler export's R2 download failed on the first attempt; standard HTTPS download
of that generated export succeeded. No backup content or credentials are committed.

Apply additive `0003_website.sql`, deploy Worker with assets, and publish only
website analytics files / footer notice to the public website. The backend source
branch remains unmerged; website publication changes no installer, release asset,
component catalog, delta or appcast. Existing Pages service binding needs no redeploy.

Known limits: browser/session IDs estimate browsers, not people; storage blocking,
privacy preferences and network failure cause undercount; event interfaces can be
spoofed. Download click counts do not prove transfer completion. Actual historical
traffic is unavailable. Automatic hourly/daily views use Asia/Shanghai. Existing
native app installation/update workflows are unaffected and were not re-exercised.


## Live deployment result

- Owner-only SQL backup restored successfully into in-memory SQLite (6 tables).
- Remote D1 migration `0003_website.sql` completed successfully (4 commands).
- Worker assets and scheduled triggers deployed; initial deployment version
  `84350cb9-6c6b-469d-9165-2ae0129e292c`.
- Private source feature commit `0d64d8a` pushed without merging private main.
- Website commit `df6295e` fast-forwarded public website main from `6c143e8`.
  Only analytics script/style, footer/script references and isolated script tests
  changed; installers, update feeds and release workflows remain untouched.
- Existing administrator login verified through the production Pages entrance;
  protected website dashboard loaded successfully with actual empty-state data.
- Command-line requests to the Pages hostname received network-level HTTP 403 in
  this environment; browser login and dashboard requests succeeded.

Final Worker version after aligning login copy:
`c71459b6-9d26-459a-97bb-f03e89aee44b` (source `ca38667`).
Published website HTML was fetched successfully with the new analytics reference.
Real browser navigation to `#updates` was recorded end to end: PV/UV/session,
country/region, desktop/macOS/browser and updates landing all appeared in the
protected production dashboard. The initial live counts include these genuine
rollout-verification browser visits; no synthetic payload or download click was
injected. Actual collection began at 2026-10-21 11:52:02 Asia/Shanghai.
