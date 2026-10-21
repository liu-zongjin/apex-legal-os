# Download package platform breakdown

Base / recovery point: `bdf632e`. Feature branch: `codex/admin-download-platforms-20261021`.

## Scope

Reuse existing `downloads` target aggregates and historical events; no API, schema,
website collector, installer or update feed changes. Move the breakdown immediately
after headline cards and show all three targets (Apple Silicon macOS, Intel macOS,
Windows), click counts, per-target distinct browsers and click share. CSV includes
zero-count targets. Existing date/device filters apply; device means visiting device.
Cross-target browser counts must not be summed as distinct people or installations.

## Verification

- Public-admin tests: 18 passed, including all targets, repeated clicks, per-target
  deduplication, cross-OS package clicks, device filters, zero rows and percentages.
- APEX fast and extended passed: 1031 tests, 13 existing skips for extended.
- Wrangler dry-run and production deployment succeeded; exactly index.html and
  website-admin.js assets changed. Worker version:
  `90f47291-9e95-43c6-b5e0-2de342d13257`. Existing D1 and service binding retained.
- Before deployment, live browser accessibility showed 3 historical clicks:
  Windows 2 clicks / 2 visitors and Apple Silicon 1 click / 1 visitor.
- Post-deployment browser connection timed out; native Chrome refresh produced a
  blank observation, so final production visual verification remains unconfirmed.
  No synthetic production events or test download clicks were sent.

Unrelated concurrent case-editor changes remain outside this commit. Feature source
is pushed separately and not merged into main pending user review.
