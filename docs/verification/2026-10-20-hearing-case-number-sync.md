# Saved hearing numbers populate case detail

## Behavior and consumers

The shared saved-hearing ledger callback now also merges its linked case's number
metadata. This covers manual creation/editing, recognition-confirmed saves,
document imports and judicial SMS outputs. Series batch hearing creation reuses
the same service. Recognition previews alone do not write case data.

The existing case-detail number table, case lookup, snapshots and series children
consume the same `case_manager_case_numbers` source. API and database schemas are
unchanged. Only the associated case is updated; case stage, existing nonempty
manual metadata and filing/service/effectiveness dates are preserved. New numbers
are appended; whitespace/bracket variants are deduplicated, and legacy combined
numbers are extracted without appending their annotations. Number type follows
the number's recognizable instance code before the reminder label. Unknown type
remains blank. Hearing time never becomes a filing date.

## Verification

- `python3 -m unittest tests.test_hearing_case_numbers tests.test_series_manager tests.test_judicial_messages`: 55 tests pass.
- `python3 scripts/apex_guard.py extended`: 988 tests pass; source syntax, registry,
  secret checks and 841-route compatibility check pass.
- Isolated tests cover ordinary linked cases, separate first/second-instance
  numbers, normalized duplicates, empty-field filling, retained manual dates and
  courts, combined/annotated legacy numbers, empty/deleted/missing cases,
  transaction rollback, actual shared ledger callback, selected series child
  batch creation, preview/backup/application and repeat repair.
- Live historical preview scanned 170 nonempty hearing records. Explicit repair
  backed up SQLite before applying changes from 39 hearings to 37 cases. It added
  35 number rows; all 330 existing rows, their original numbers, manual nonempty
  values and procedural dates were compared against the backup and preserved.
  Actual fills/additions have case audit entries. Repeat preview reports zero
  changes; database and backup quick checks report `ok`.
- The screenshot's linked case now has both its existing first-instance number
  and the hearing's second-instance number with the corresponding intermediate
  court. This was verified through the stored fields. Reopen case detail to load
  the updated data; no live UI claim is based solely on this database check.

The backup remains in ignored runtime `data/backups/` with a
`before-hearing-case-numbers-20261020-182058-` prefix. Source recovery before this
change is `a2bdeef`. Unrelated edits to `AGENTS.md` and
`docs/PUBLIC_UPDATES_AND_ADMIN.md` remain untouched. No public build was released.
