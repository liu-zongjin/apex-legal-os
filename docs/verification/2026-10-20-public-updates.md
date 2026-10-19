# Public updates and administrator statistics verification

Verified 2026-10-20 on Apple Silicon. Recovery checkpoint: `59d94dd` (unchanged
main code at `012b306`). Work branch: `codex/public-updates-admin-20261019`.
The running private app, its database and attachments were not replaced or tested.

## Passed

- Repository extended checks: 960 tests passed. Final targeted update/native
  contracts passed; release URL regression added afterward also passes.
- Worker tests: five groups passed against temporary Miniflare D1: login/origin/
  cookie/expiry, unauthenticated denial, bounded events/rate limiting, per-device
  deduplication, and stale-snapshot preservation on GitHub failure.
- Public native app compiled against the official checksum-pinned Sparkle 2.10.0
  framework; existing private shell also compiled independently.
- A fresh, sanitized complete public app was frozen and built in an ignored test
  directory. Its packaged backend self-test passed. Bundle has no runtime database,
  credentials or private case data; ZIP contains only Stella.app. Deep/strict code
  signature verification passed. Third-party notices include Sparkle and jose.
- Real packaged server started with a temporary home/runtime, published a unique
  launch readiness marker, rejected a second process sharing that directory,
  handled normal SIGTERM shutdown, and removed its readiness marker. On build
  change it preserved the anonymous database marker and upload fixture, and made
  a readable pre-upgrade SQLite backup. Uvicorn 0.33 intentionally re-raises the
  captured SIGTERM after graceful shutdown; exit status -15 is expected.
- Two anonymous miniature apps generated signed full ZIP enclosures and a smaller
  delta. Applying that delta reproduced target metadata and file bytes. No test
  feed or fixture was published to the website. Actual candidate feed and archive
  signatures were also verified by upstream tools.
- Admin UI checked at 1440 and 1024 pixels in light/dark appearance without
  horizontal overflow. Test-only counters did not enter production D1.

## Deployment and remaining external verification

The Worker and separate D1 database were created and deployed using the user's
Cloudflare account. Independent administrator password and session secrets are
stored as Worker secrets. No Cloudflare Access subscription was activated and no
payment method was entered. The initial real public GitHub asset snapshot was
synchronized from GitHub: 7 requests. Reporting installation rows remained zero.

Production URL: https://stella-public-admin.cuplsilence.workers.dev

This network cannot reliably reach the default workers.dev hostname: observed
DNS responses include non-Cloudflare addresses, timeouts and connection resets.
Official Cloudflare deployment/API calls succeed. No system DNS/proxy settings
were changed. The user requested retaining the default address while diagnosing.
Production browser login, client-to-production heartbeats and cron refresh have
not been verified end to end; no claim of complete external availability is made.
The dashboard explicitly marks missing/stale download snapshots. Do not silently
publish an installer on the assumption that this network problem is resolved.

A real Sparkle update prompt/install/relaunch between two released applications
has not been exercised. The miniature-app patch round trip proves patch generation
and bytes, not macOS installation permissions, Gatekeeper or update UI behavior.
Developer ID signing and notarization remain unconfigured, consistent with prior
ad-hoc distribution. No new installer/feed was uploaded to GitHub Releases/Pages.

Candidate artifact (local test only):
`.tmp/public-update-package-20261020-final/Stella-macOS-AppleSilicon-v1.0.1-2026102001.zip`

SHA-256: `61217e03f82008db9c3b74db9f4a3d99fd562eebcb41f32d8338a603cecc4a30`

Source snapshot for the candidate: `fb161ad`. Subsequent changes affect feed
preparation/tests and verification documentation, not the embedded application.
The production administrator password is in the owner-only local file
`~/.config/stella-admin/credentials.txt`; it is not in Git or this report.
