# APEX System Map

## Runtime

APEX is a single-user hybrid macOS application. `dist/APEX.app` is an AppKit shell
containing one WKWebView. It loads the local FastAPI service at
`http://localhost:8000`. The Python service owns business logic, SQLite access,
file processing, AI integrations, scheduled work, and browser automation.

The optional anonymous mobile pilot is a separate Docker runtime. It serves the
same FastAPI and web assets with a separate, fictional SQLite database and has no
connection to the Mac application's data directory. Its container entry point is
`scripts/mobile_pilot_entrypoint.py`; see `APEX_MOBILE_CLOUD_PILOT.md`.

```text
APEX.app (AppKit)
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

## Stability boundaries

- FastAPI route method, path, request parameters, and documented response fields
  form the browser/backend contract.
- The Efficiency Center preference endpoint keeps its existing `order` list and
  optionally stores per-entry `groups` and `subtitles` maps. Older order-only
  clients remain supported; all three values are saved in one SQLite transaction.
- Shared component options and emitted `apex:*` events form the page/component
  contract.
- Native message-handler names and cross-frame message names form the WebKit
  bridge contract.
- SQLite changes go through `backend/migrations.py`; startup schema helpers may
  remain during gradual migration but may not introduce new unnumbered changes.
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

## Change flow

Focused changes run the fast guard. Changes to a boundary above are cross-module:
generate an impact report, update compatibility documentation, run the extended
guard, and inspect every registered consumer.
