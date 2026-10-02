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
