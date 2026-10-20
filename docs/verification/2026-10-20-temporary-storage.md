# Temporary storage purpose and selected cleanup

Changed storage management only: the main shell now treats temporary storage as
optional, opens per-entry advice, and requires explicit selected deletion.
The `.tmp` category still reconciles with the existing total. A second whole-item
size explains any nested cache/log bytes already listed in other categories.

The live inventory on 2026-10-20 contained 41 entries, 4.39 GiB of temporary files,
and 3.32 GiB of old packaging copies eligible for priority selection. The latest
candidate is retained by default. SDK/test artifacts are optional; SQL, database,
backup, sensitive and unknown files are protected. Directory names are narrow
allowlists; arbitrary directories ending in `-ui` do not qualify.

Cleanup validates the complete explicit name/revision selection before deletion,
checks open files with lsof, and rejects stale revisions, protected files,
external links, invalid paths or unavailable occupancy checks. No-selection
legacy temp_files requests fail closed. No automatic cleanup was added.
Metadata/open-file checks are point-in-time checks; users should finish build
and verification tasks before cleaning their artifacts.

Validation:
- APEX extended guard: all 976 tests passed, including eight new isolated safety
  tests. API routes remain unchanged; temporary_items and selected request items
  are additive fields on existing routes.
- Storage detail, export and temporary UI harnesses passed in light/dark at
  1440, 1024 and 390 widths. Search, bounded pagination, no default selection,
  priority-only selection, confirmation reset, revision payloads and Escape
  focus return were exercised with mocked cleanup.
- Authenticated live service returned detailed rows. A browser opened the real
  main app and temporary detail panel: zero selected items, zero cleanup calls.
  Live category/detail byte totals matched. No live files were deleted.
- Main/case shell asset references advanced together to shell 266; offline shell
  and theme tests passed. No public installer was rebuilt or published.

Recovery base: 08a557d. Work branch: codex/temporary-storage-details-20261020.
