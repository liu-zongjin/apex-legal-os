# Admin statistics synchronized with the current website

Recovery point: application `a7f3ac5130bbe2901697c4303bd7dcc9f9c68300`;
website `77b4831` (origin/main, fetched before editing).
Application branch: `codex/admin-current-website-20261027`.
Website branch: `codex/website-analytics-20261027`.

Live HTML and analytics assets were fetched from the official GitHub Pages site.
The current guide has Mac 1.1.5 (Apple/Intel, Quark/GitHub), Windows 1.1.7 test
complete offline ZIP on Quark, and a secondary 1.1.6 GitHub online installer.
No product-version values are added to telemetry or hardcoded into the dashboard.

## Behavior

- `download-guide` distinguishes download.html pageviews/sections from home.
- Optional download `channel` accepts only quark/github. Old events and cached
  old collectors remain accepted as unknown; historical classifications stay intact.
- Dashboard channel counts, distinct visitors and CSV share existing date/device
  filters. Per-channel or per-system visitors cannot be summed as unique people.
- GitHub snapshots count Windows setup.exe installers as well as Mac ZIP/DMG.
  Component ZIPs, deltas and helper files remain excluded. Quark file transfers
  are unavailable; dashboard copy explicitly distinguishes clicks and requests.
- Migration 0004 adds one defaulted column; no historical event rewrite.

## Validation

- Repository preflight passed; initially clean application checkout.
- Extended checks: 1177 tests, 26 skips, passed.
- Public-admin tests: 20 passed using temporary Miniflare D1.
- Website collector tests: 6 passed; guide landing, both channels, offline ZIP,
  online installer, component exclusion, privacy, opt-out, storage and visibility.
- Isolated SQLite migration verified an existing event survives with unknown channel.
- Browser checks using local anonymous fixtures: all three tabs, filters, CSV,
  no JavaScript errors, 1440x900 light, 1024x768 dark, 390x844 mobile, no page overflow.
- Screenshot examples and CSV: `outputs/stella-admin-20261027/` in parent workspace.
- Wrangler deployment dry-run passed with existing D1/auth/rate-limit bindings.

## Deployment sequence

1. Export production D1 to an owner-only ignored file and verify the export.
2. Apply additive 0004 migration, then deploy the Worker/assets.
3. Publish only website collector v4 and script-version references.
4. Verify authenticated summary/channel response and public script without
   injecting synthetic production visits/downloads or publishing test messages.

At preparation time Cloudflare OAuth had expired. A proxied retry confirmed an
expired credential; browser login was opened for the owner. No production schema
or website collector was changed before authentication. Application installers,
Sparkle feeds, components and live local business data are outside this update.
