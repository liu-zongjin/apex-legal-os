# Administrator connectivity repair

Date: 2026-10-20 (Asia/Shanghai).
Recovery checkpoint: `8f4c555`, on `codex/public-updates-admin-20261019`.

## Result

New public entrance: **https://stella-admin.pages.dev/login**
New telemetry endpoint for future package builds:
**https://stella-admin.pages.dev/v1/events**

The Pages Function calls `stella-public-admin` through a private Service Binding,
not an HTTP redirect or a public fetch to the blocked workers.dev hostname. The
same Worker owns authentication, D1, rate limits, assets and scheduled jobs. The
existing generated password, database and cookie security policy are retained.
No card or Cloudflare Access subscription was used. The gateway fails closed with
503 if the bound service is unavailable; every route is forwarded for auth checks.

Real deployment also uncovered HTML routing failures: auto-clean-URL asset
redirects had been wrapped as empty 200 responses, and disabling automatic handling
then required an explicit index.html mapping for the authenticated root. The fix
uses explicit HTML paths, disables automatic HTML redirects, and preserves status
codes. Regression tests cover both cases.

## Checks

- Nine Worker/entrance tests passed, including private forwarding, preservation of
  origin/cookies/body, failure handling, authentication, D1 deduplication, bounded
  events, and the HTML route regressions.
- Repository extended checks: **961 tests passed**.
- Live HTTPS requests succeeded for login HTML, rejection of anonymous stats access,
  real password authentication, secure session cookie, protected dashboard root,
  script, summary API, event-validation failure and logout. Credentials were read
  locally without printing or putting them into request URLs/process arguments.
- The real summary returned 7 GitHub full-package requests, zero reporting devices
  and zero running devices. No fake installation records were written to D1.
- After one transient Node connection timeout, a new series of ten direct probes
  succeeded: 10/10 HTTP 200 responses with the real password form, 307–2928 ms.
  Separate TLS-verified probes to both current Pages IPv4 addresses also succeeded.
  These are bounded current-network observations, not a permanent/global SLA.

## Local browser proxy finding

The active Wi-Fi interface is en0. macOS has an existing local HTTPS proxy enabled.
Requests explicitly routed through that existing proxy timed out for BOTH the old
Worker and new Pages entrance, while direct requests to the Pages entrance worked.
This explains why a reachable service can still fail in the user's browser.

The proposed repair is a single-host proxy bypass for `stella-admin.pages.dev`,
preserving the existing proxy configuration and bypass entries for all other
traffic. Approval was requested before changing this system network setting.
Do not distribute a system proxy modification inside the public app.

The owner-only local administrator information file has been updated to the new
URL without changing its password. Previously built ignored installer candidates
contain the old endpoint and must be rebuilt before release. The public installer
and website download package were not replaced by this connectivity repair.
