# API Compatibility

- Adding an optional response field is compatible.
- Removing or renaming a route, parameter, or response field is breaking.
- Changing a field type, meaning, default, ordering guarantee, or error behavior is
  breaking even when the field name stays the same.
- Breaking changes require an impact report, a compatibility adapter or migration,
  updated consumers, contract snapshot, tests, changelog entry, and explicit
  verification of every registered consumer.
- API snapshots describe surface compatibility; behavior tests remain required.

## Knowledge center search

`GET /api/legal-knowledge/search` accepts optional `offset` (default 0).
`results` contains at most `limit` cards, while `total` is the number of matching,
current, distinct cards before pagination. Text match is required when `q` is
nonempty; `case_id` and favorites affect ranking only. Older callers that omit
`offset` still receive the first page. The knowledge center is the only registered
consumer of this route and uses `total` to offer additional pages.

## Knowledge directory (2026-10-07)

- `PUT /api/domains/categories/{category_id}/rename` takes `{name}`, returns
  `{id,name}`, and preserves IDs, recognition keywords and article associations.
  Sibling duplicates return 409; old names use the existing suppression table.
- `GET /api/articles/offline-snapshot` is version 3 and adds `subcategory_ids`
  and `classification_status` to each article. Version 2 remains readable for
  general offline browsing; child and pending filters require the new fields.
- Saved view records retain an optional `subcategoryId`. A missing or removed
  child ID clears the child filter and falls back to the recorded parent domain.
- Category, child and tag reorder reject duplicate, missing, stale or foreign
  IDs with 409 before writing any order. `POST /api/tag-groups/reorder` accepts
  optional `category_id`; legacy callers infer the single parent from IDs. The
  collection contains the visible tag rows, consistent with the directory API.
- Legacy manager entry functions route to the unified manager. Existing order
  preferences remain valid. Locks are replaced by the hover/click expansion
  preference; searching never modifies article filters or saved expansion paths.
