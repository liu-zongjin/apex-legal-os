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
