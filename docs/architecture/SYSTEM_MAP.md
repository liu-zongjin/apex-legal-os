# APEX System Map

## Runtime

APEX is a single-user hybrid macOS application. `dist/APEX.app` is an AppKit shell
containing one WKWebView. It loads the local FastAPI service at
`http://localhost:8000`. The Python service owns business logic, SQLite access,
file processing, AI integrations, scheduled work, and browser automation.

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

## Stability boundaries

- FastAPI route method, path, request parameters, and documented response fields
  form the browser/backend contract.
- Shared component options and emitted `apex:*` events form the page/component
  contract.
- Native message-handler names and cross-frame message names form the WebKit
  bridge contract.
- SQLite changes go through `backend/migrations.py`; startup schema helpers may
  remain during gradual migration but may not introduce new unnumbered changes.
- Aggregate runtime metrics live only in process memory. The settings performance
  panel never records request bodies, query strings, client names, or file paths.

## Change flow

Focused changes run the fast guard. Changes to a boundary above are cross-module:
generate an impact report, update compatibility documentation, run the extended
guard, and inspect every registered consumer.
