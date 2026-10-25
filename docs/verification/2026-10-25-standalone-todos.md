# Ordinary todo save repair — 2026-10-25

The user confirmed that an AI-recognized todo could not be saved with an empty
case association. The same restriction affected manual todos. Save now accepts
an ordinary todo with NULL case_id and an empty case title. It never creates a
placeholder case; selecting a valid existing case still creates a linked todo.

The repair includes listing/search, offline snapshots, dashboard counts, homepage
reminders/cache invalidation, event-calendar reads, calendar synchronization,
editing/reassociation, deletion and idempotent completion. Ordinary completion
records status/date without a case project/ledger. Linked completion keeps its
existing project/ledger path. The form labels the association optional and Save
errors now use the existing toast instead of an unhandled rejection.

Migration 26 is backup-first via the numbered migration runner. It preserves
existing records, incoming shortcut links, indexes/triggers and original IDs,
including the deleted-ID AUTOINCREMENT high-water. Fresh database schema definitions
are nullable too. The local service reported current source after automatic reload;
a before-v26 database backup was confirmed present. No live business record was
created, edited or deleted during verification.

Verification:

- 8 standalone-todo tests exercise the actual reminder route functions and SQLite
  on an anonymous temporary database: save/list/search, recurrence calendar events,
  attach/detach/edit, ordinary and linked completion, repeat completion, delete,
  validation, homepage cache invalidation and migration preservation.
- 4 numbered-migration tests passed, including repeat safety and automatic backup.
- Extended suite: initially 1,157 tests passed; the final integrated source, including
  the separately completed OCR settings change, passed 1,169 tests with 26 skipped.
- WebKit and Chrome browser flows now run the actual Save API against the anonymous
  temporary SQLite fixture after mocked AI recognition. They verify drawer closure,
  the saved ordinary todo in the list, calendar availability and no new case row.
  They retain the four-menu navigation and async-drawer isolation checks.
- Live AI response quality and actual iCloud writes are not exercised by these
  isolated tests. The existing calendar sync adapter remains the shared path.

Recovery baseline: `fc26293`, before standalone todo support. Source changes remain
in the canonical checkout, with shell 285; the concurrent OCR bootstrap asset version is retained.
