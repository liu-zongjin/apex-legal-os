# APEX System Map

## Runtime

APEX is a single-user hybrid macOS application distributed as `dist/Stella.app`. The AppKit shell
containing one WKWebView. It loads the local FastAPI service at
`http://localhost:8000`. The Python service owns business logic, SQLite access,
file processing, AI integrations, scheduled work, and browser automation.

The optional anonymous mobile pilot is a separate Docker runtime. It serves the
same FastAPI and web assets with a separate, fictional SQLite database and has no
connection to the Mac application's data directory. Its container entry point is
`scripts/mobile_pilot_entrypoint.py`; see `APEX_MOBILE_CLOUD_PILOT.md`.

```text
Stella.app (AppKit)
  └─ WKWebView
       ├─ frontend/index.html + app.js + style.css
       ├─ feature pages loaded as same-origin iframes
       └─ HTTP / postMessage / native message handlers
              ↕
        FastAPI backend
          ├─ legal_kb.db
          ├─ uploads and case folders
          ├─ AI, mail, Feishu, Quark and legal-data integrations
          └─ court browser automation and background schedulers
```

## Ownership boundaries

- `native-shell/`: window lifecycle, macOS menus and shortcuts, notifications,
  permissions, downloads, clipboard, biometric bridge, and WebKit recovery.
- `frontend/`: presentation and browser-side interaction. Shared browser assets
  use the `apex-*.js` / `apex-*.css` prefix.
- `backend/`: APIs, persistence, integrations, document generation, and workers.
- `tests/`: isolated tests using temporary or in-memory data.
- `scripts/`: maintenance, preflight, contract, release, and diagnostic tooling.

Runtime data and credentials remain outside version control even when physically
located inside the project directory. See `.gitignore` and `AGENTS.md`.
`LEGAL_KB_RUNTIME_DIR` may redirect the database, uploads, and article images to
an isolated runtime directory; the local app defaults to its existing base
directory.

## iPhone offline shell

The Home Screen entry `/case-manager` is a public, data-free application shell.
Its versioned CSS/JavaScript and Service Worker are public so an expired session
cannot prevent repair or upgrade; every case API and offline-snapshot API remains
authenticated. `GET /api/pwa/session-status` exposes only reachability,
authentication state, and the shell version.

The Service Worker validates the shell version header and content type before a
staged cache becomes active. Navigation is cache-first and keeps one previously
verified release for rollback. Case snapshots continue to use the existing
`legal-kb-case-manager` IndexedDB database, while pending case mutations retain
their existing localStorage queue. Shell repair may remove shell caches and the
worker registration, but must never remove either user-data store.

Legacy top-level case entries enter the existing main tab host at /?workspace=cases
and reuse its mobile floating navigation. Case iframes are never redirected.
The worker prepares the main
page and its required assets from public data-free /app-shell and static assets.
Installation requires a complete main shell even in a fresh standalone store.
Manifest identity remains /case-manager, but new installations start at /. Legacy
standalone case HTML redirects to the main host before app startup; iframe HTML
does not redirect. Expired case iframe authentication opens login in the parent. It never
caches login HTML. Offline root navigation uses a separate completion marker;
online root navigation still respects login responses. No business API becomes
public and no cached user data is deleted during this upgrade.

## Stability boundaries

- FastAPI route method, path, request parameters, and documented response fields
  form the browser/backend contract.
- The Efficiency Center preference endpoint keeps its existing `order` list and
  optionally stores per-entry `groups` and `subtitles` maps. Older order-only
  clients remain supported; all three values are saved in one SQLite transaction.
- Shared component options and emitted `apex:*` events form the page/component
  contract.
- Active-case menus share `apex-case-picker.js` and its CSS. Popup and inline
  hosts keep their own selection actions; the component owns browsing, keyboard
  navigation, recent selections, client grouping, and full series-child names.
  `GET /api/case-manager/case-lookup` supports bounded offset pagination;
  `items` remains compatible, and `has_more`, `next_offset`, and `folder_bound`
  are additive. Every active series child remains selectable by its original ID.
- Native message-handler names and cross-frame message names form the WebKit
  bridge contract.
- When the disk source changes, the backend returns 503 until the service reloads.
  Browser navigations receive a self-recovering waiting page; API callers retain
  JSON status. The native shell also intercepts local main-frame 503 responses
  and reloads only after `/api/server-status` reports current source.
- Knowledge center `apex:knowledge-prefill-ask` messages carry version 1 and a
  question. The parent accepts them only from a knowledge center tab iframe.
- SQLite changes go through `backend/migrations.py`; startup schema helpers may
  remain during gradual migration but may not introduce new unnumbered changes.
- The knowledge article editor saves title, HTML body, and per-article margins
  through `PUT /api/articles/{id}/editor` in one transaction. The request includes
  the original title and body for conflict detection. `GET /api/articles/{id}/editor-layout`
  loads margins; legacy title and content routes remain available to other clients.
- Article deletion uses `article_trash` snapshots rather than a permanent first
  delete. `DELETE /api/articles/{id}` and `DELETE /api/articles/bulk` preserve the
  article and cascading rows for 30 days; trash list, restore, and purge APIs
  manage those snapshots. An hourly backend task removes expired snapshots,
  including immediately after service startup. Original uploaded files are not
  removed by article-trash cleanup.
- Knowledge classification keeps `articles.domains` as the compatible top-level
  field. Numbered migrations 12-13 add approved two-level taxonomy nodes, per-article
  child choices and exclusions, a durable classification queue, suggestion evidence,
  and persistent child ordering. Article inserts and title/body edits enqueue
  classification; migration 13 queues historical articles once. Rules propose
  concrete child topics from titles and summaries, with configured AI used when
  the rules cannot identify an existing or proposed child. Suggestions need user
  approval before joining the catalog. Migration 16 supplements historical child-topic
  suggestions for previously uncovered domains without changing article choices.
  AI fallback checks coverage for each identified root and retains rule matches. `GET /api/domains`
  adds child nodes and counts without removing legacy `domain` and `count` fields;
  `GET /api/articles` accepts optional `subcategory_id` and classification status,
  while `GET /api/domains/pending-count` drives the visible review queue. Manual choices are
  retained across reclassification. Approving a category queues affected historical articles for automatic reclassification.
  Optional manual reclassification previews actual root and child assignment differences
  and applies only changed articles in batches, preserving manual choices and exclusions. The category-management modal also links
  to the existing custom-tag ordering editor and offers persisted child ordering.
  The review UI pages large suggestion sets through
  `GET /api/domains/suggestions/page` with search and filter parameters; the
  original array-returning suggestions route remains available to older clients.
- Case archive assignments, saved checklist snapshots, and export history are
  kept in SQLite by `backend/case_archive.py`; the bound local case folder
  remains the material source of truth. Saving a checklist does not generate an
  electronic case file. Each export is a separate version under `APEX案卷归档`
  and never changes case status.
- The archive workbench embeds the existing `/case-files` page in an archive picker
  mode. Its file columns, sorting, search, selection, and preview remain owned
  by that page; same-origin `apex:archive-*` messages carry selected relative
  paths and status updates to the archive page.
- Aggregate runtime metrics live only in process memory. The settings performance
  panel never records request bodies, query strings, client names, or file paths.
- Private Mac backup management uses `GET /api/backup-management`,
  `PUT /api/backup-management/settings`, and
  `DELETE /api/backup-management/files/{category}/{name}`. Settings live in
  `LegalKBBackups/backup-settings.json`; the schedule updates the existing
  launchd agent. File deletion accepts only generated names directly inside the
  configured database or uploads backup directory.

## Online reading downloads

`backend/court_dossiers.py` owns `/api/case-manager/court-online/readings`
and `/api/case-manager/court-online/downloads`. Numbered migration 17 stores
account-scoped reading records, jobs, and file state. Session headers and output
directories come from the existing court integration; signed download URLs stay
in memory and are resolved again before continuing a job. Cookie/Authorization
headers are sent only to the court origin, not to OSS file hosts.

One job executes at a time with up to three streaming transfers. Partial files
use validated Range/If-Range or restart when unsupported. Startup recovery pauses
interrupted jobs; account switching pauses jobs before replacing the session.
ZIP64 creation runs off the event loop, preserves original files and order, and
includes a manifest. Partial success is visibly distinct from complete success.
The independent `/court-online-downloads` page uses the shared lifecycle and only
polls while active. Application-material test tasks use the same executor but a
separate labeled source, with no application documents in dossier downloads.

The current account has no effective open dossiers. Directory-tree parsing has
fixture coverage; independent viewer integrations remain pending a permitted
sample. If the normal directory contains no downloadable files, show a clear
notice and direct the user to the official viewer rather than claiming success.

## Change flow

Focused changes run the fast guard. Changes to a boundary above are cross-module:
generate an impact report, update compatibility documentation, run the extended
guard, and inspect every registered consumer.

## AI gateway protocols

CC2API Claude Code-only key groups use the official Claude Code headless client,
installed at the pinned version with `scripts/install_cc2api_runtime.py` into
ignored `data/cc2api-runtime`. `backend/cc2api_bridge.py` passes credentials only
in the child environment, derives the base URL from the configured Messages URL,
and normalizes the client's JSON result into the existing choices contract.
Each call uses temporary configuration, bare mode, disabled built-in/MCP tools,
no session persistence and nonessential traffic disabled. Timeout and cancellation
terminate the child process. Conversation history and system instructions are
passed explicitly; no unrelated project or user configuration is loaded.
The gateway catalog is distinct from official model availability. Client output
limits use Claude Code's token environment setting (minimum 256); temperature
is managed by the official client rather than exposed as a gateway parameter.

## Case AI management

Efficiency Center places 案件 AI 管理 below AI增强. The CASE_AI tab mounts the
existing AI chat panel and saves a separate `ask_history_case_database` history.
`POST /api/ask` with `source_mode=case_database` returns before KB/MCP/skill routing.
`backend/case_ai.py` discovers case-management, case-archive and case-linked tables,
including all synced 一张网 records, filing audits, hearings, deliveries, messages,
attachments and original JSON fields. Model-planned read queries run on one SQLite
snapshot through a restrictive authorizer, with bounded rows, text and execution
time. Aggregation scans all matching records; truncated details require pagination.
Authentication settings and secret columns are excluded. Answers include database
query evidence and snapshot time, distinguish sync dates from real-time portal
state, and link sources back to case management or 一张网. No schema change.
