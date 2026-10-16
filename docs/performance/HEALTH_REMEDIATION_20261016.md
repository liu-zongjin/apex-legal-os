# Stella health remediation — 2026-10-16

Implementation branch: `codex/stella-health-20261016`. Recovery checkpoint: `eab278a`.

| Audit item | Implementation | Verification |
| --- | --- | --- |
| 01 Request source scans | Fail-closed sampled SourceMonitor; request reads memory | IO-free status and expiry tests |
| 02 Runtime files in source watch | Pre-recursion pruning, plural profiles and previews excluded | Temporary profile/preview mutation test |
| 03 Duplicate recommendations | Shared pending Promise, transition-only layout update | Anonymous browser request counts |
| 04 Blocking async work | Sync image route uses FastAPI worker; OS commands off event loop | Concurrency and file-route tests |
| 05 Snapshot N+1 | Batch hydration and one query-only read scope; client coalescing | Anonymous snapshot parity and timing |
| 06 Orphan records | Backup-first explicit maintenance; lossless archive plus reattachment UI | Cascade/BLOB/idempotence/conflict tests |
| 07 Repeated relation scans | Durable input revision triggers; cached unchanged rule scan | Revision invalidation and scan regression |
| 08 Cache deletion | Native HTML revalidation; immutable versioned assets; shell 255 | Native compile, browser cache and offline tests |
| 09 Serial startup | Concurrent cache initialization and early articles; unknown network state | Slow probe and duplicate-load browser checks |
| 10 Import side effects | One migration call, marked backfills, deferred volume verification | Migration and startup contracts |
| 11 FTS bloat | Narrowed Python/MCP update trigger, explicit backed-up optimize/VACUUM | Unrelated update test; maintenance integrity |
| 12 Hidden-page work | Origin-checked lifecycle, serialized polls, shared file watches | Lifecycle harness and watch cleanup |
| 13 Monolithic resources | Reproducible compact bootstrap/CSS and on-demand AI async chunk | Build manifest and anonymous browser coverage |
| 14 Telemetry gaps | Outer ASGI timings/categories, loop lag, capability labels, frame DOM counts | Performance tests and WebKit checks |
| 15 Fixed launch delay | Optional readiness-driven launch, preserving explicit duration preferences | Ready event and settings browser checks |
| 16 Unreachable Python | Removed both unconditional-return tails | Full feature suite |
| 17 Shadowed highlight | One implementation; explicit fuzzy-only list mode | Special-character and note/list coverage |
| 18 AI latency | Request-isolated pooled transports, separate background capacity, direct-answer stream | Mock-provider stream/cookie/privacy/cancellation tests |

## Data and compatibility

Migration 24 adds recovery storage, relation revisions, and maintenance markers. Runtime rows are not automatically discarded by migration. `scripts/maintain_health.py` reports only unless `--apply` is supplied; every apply creates a SQLite backup. Repair preserves orphan rows and all declared cascading descendants before removing invalid references in one transaction. Recovery rows remain after reattachment. Existing APIs and whole-answer history remain authoritative. The new stream only serves direct-AI requests and emits final-answer text; planners, reasoning and background extraction do not enter the preview.

Generated browser assets are built by `npm ci && npm run build:frontend`; canonical `frontend/app.js` and `style.css` remain the readable source and compatibility assets. The Service Worker pre-caches the lazy chunk so it works offline. Business data, cookies, IndexedDB and pending edits are retained.

Historical OA, old distribution scripts, old logos and side worktrees remain candidates, not proven unused runtime code. They are outside the 18 applied findings and are preserved pending an explicit retirement decision.

## Review and delivery

The final review must include full extended tests, meaningful new regression tests, Chromium/WebKit anonymous workflows, offline and cold/warm cache behavior, native compilation, maintenance integrity and a clean diff. Runtime code must be installed as one coherent release, not edited in place while serving requests. Do not merge this cross-module branch into main until the user has confirmed the resulting pages/behavior.

## Verification completed

- Extended repository guard: 908 tests passed; syntax, shared registry, API contracts and secret checks passed.
- Reproducible frontend build: bootstrap 1,145,833 bytes vs canonical 1,459,412; optional AI chunk 59,797; CSS 817,992 vs 1,022,032 bytes. These are uncompressed asset sizes, not an end-to-end startup percentage.
- Anonymous Chromium and WebKit: 1440x900 and 1024x768; home, case management, dark/light, direct AI stream, diagnostics and recovery chooser. No uncaught browser errors. Versioned bootstrap/CSS refresh transferred zero bytes from the network.
- Additional Chromium/WebKit: delayed 800 ms reachability probe still issued one article request and one recommendation request; four ordinary/archived/series-child snapshot details matched the existing detail API. Document generator, personal center, file page, filing and article entry rendered.
- Chromium verified shell v255 installation and offline root reload with 10 cached article cards. Business stores remained available.
- Native optimized Swift build passed. Production provider calls, court submission, mail/Feishu sending and external file-system actions were not exercised; the AI stream used an anonymous mock provider.

## Second review and debugging

Resolved the direct-AI final-content context omission found by full-browser streaming (previously returned only a whole result). Added a regression asserting that final context is reset. Verified disconnect cancellation, cookie isolation, no reasoning deltas, final history ownership, unchanged relation reuse and note-edit invalidation. Image proxy now caps active remote fetches at eight and closes responses/sessions on every exit, retaining local worker capacity. Removed legacy full app/CSS from the new shell pre-cache list to avoid downloading both canonical and generated versions during installation; legacy URLs remain compatible.

No unresolved blocker was identified in the reviewed scope. Synthetic browser timings are not a same-data comparison with the production baseline. Deployment/maintenance observations are recorded separately after installation.

Recovery follow-up: after a parent is restored, dependent preserved records may
have no missing reference. The restore endpoint now permits restoring their
original relationships with an explicit null parent, while still rejecting
unnecessary reassignment, conflicting IDs and incomplete dependencies. The UI
provides a confirmed original-relationship restore action; a parent/child BLOB
regression verifies the full recovery sequence.

## Installed result

Installed into the local runtime on branch `codex/stella-health-20261016` (no main
merge). Native app rebuilt and relaunched. Database backup preceded migration 24.
Explicit maintenance preserved 70 rows including dependent records, resolved all
34 FK violations and passed integrity checking. During compaction the database
shrank from 302,469,120 to 145,666,048 bytes. Original article/case counts and the
sum of active plus preserved note/claim counts matched the pre-maintenance totals.
Backups remain in ignored `data/history_backups`.

Local read-only status samples (12 each) had median 73.94 ms before and 2.69 ms
after. The installed case snapshot returned 59 active and 92 archived cases in
438.72 ms; its measured snapshot phase was 131.3 ms. A temporary database copy
showed 193.24 ms on first relation scan and 0.64 ms for its cached repeat. These
are short diagnostic samples; the original audit and current database are not
identical, and they do not establish an overall app startup percentage.

Post-install review identified mail-server reads and the home reminder aggregate
inside the local metric bucket. They are now classified as external; mounted
static assets use a sanitized category path even without a route object. A
regression covers these distinctions. The observed startup brand-setting request
(~652 ms) and external reminder aggregate (~2.94 s) remain recorded observations,
not evidence that all startup requests now meet the local 500 ms budget.

## Approved main integration

On 2026-10-16 the user explicitly requested synchronization and merging of all
recent changes. Main was fast-forwarded from `589fa2c` to `a45fe6b`, including the
case attachment fixes and all eighteen health remediations. The merged code tree
is identical to the installed version that passed 908 extended tests. No runtime
database, credentials, uploads or backups are part of this integration.
