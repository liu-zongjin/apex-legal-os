# User long-term memory review — 2026-10-12

Reviewed the final backend, migrations, browser management panel, main AI scopes,
case AI, selected-file queries, authentication boundary and offline shell assets.

## Findings fixed

- An answer completing after a memory deletion/edit or settings change could
  restore the former value through automatic capture. The memory settings now
  carry a monotonically increasing revision. Auto-save checks enabled flags and
  the original revision under the same SQLite write transaction as the insert.
- Saved user text could influence retrieval as if it were an instruction or a
  legal source. Prompts label it as untrusted personalization, with the current
  request and source restrictions taking precedence. The management UI uses
  text nodes for every stored value. File authoritative subqueries explicitly
  opt out so a parent request's opt-out cannot leak through nested retrieval.
- Name corrections could leave conflicting identities. Short explicit name
  statements now update the existing name entry. Duplicate auto-capture is silent.
- Main-page asset changes could strand the mobile/offline shell on older assets.
  Worker/version references now agree; the two new data-free assets join public
  shell resources. Memory APIs remain protected by existing authentication.

## Verification

- Full extended repository guard: syntax, secrets, API contract, shared-capability
  registry and all Python tests, using an isolated temporary runtime database.
- Browser harness: create/edit/search/delete/clear, cancel confirmation,
  server-error draft retention, literal HTML handling, settings, focus trapping,
  Escape/return focus, 1440×900 and 1024×768 light/dark, and 390px width.
- Backend tests: cross-conversation context, local save/list/forget commands,
  disabled and per-request opt-out, persistence, capacity, deduplication,
  automatic capture boundaries, cancellation/failure, revision races, identity
  correction, selected-file command interoperability and nested query isolation.
- Existing case AI and source-routing regressions continue to pass.
- Actual Stella toolbar displays the new management and per-request controls.

## Practical limits

Automatic capture intentionally recognizes only short explicit name and response
preference statements. Other facts require “记住：…” or manual entry. It does not
mine previous history, documents or AI answers. There is no user account switching:
the database belongs to Stella's existing single-user runtime. Actual paid model
calls and real case/document workflows were not run; those request paths were
verified with anonymous fixtures and mocked AI responses. Saved-memory management
was tested against the real HTTP route contract in isolated databases.

Recovery point before this feature: `7cde187`. Feature branch:
`feature/user-long-term-memory`. Migration 18 uses the existing pre-migration
SQLite backup mechanism. Main branch remains unchanged pending user review of
these cross-module changes, as required by `AGENTS.md`.
