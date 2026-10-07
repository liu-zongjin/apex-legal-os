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

## Mobile branding (2026-10-07)

- Public `GET /api/brand` returns revision, custom/configured flags and logo_url; public `GET /brand-logo.png` contains branding only. `PUT /api/brand` accepts a validated transparent PNG/WebP data URL or an empty string to restore default and requires the existing session or Basic authentication.
- Brand state is atomically stored under ignored `data/mobile-brand.json`; default assets remain packaged. Installation icon endpoints revalidate and render a white square without an extra mobile corner mask.
- The manifest name is Stella, while id/start_url remain `/case-manager`. Mobile shell v231 includes shared brand adapters and verified offline main-page caching. Existing case IndexedDB, queued edits and historical cache schemas are unchanged. Existing iOS home-screen icons may need to be re-added using Safari.

## Offline main navigation (2026-10-07)

- Authenticated `GET /` adds `X-APEX-Shell-Version`; login responses do not carry it. Authentication and business API contracts are unchanged.
- The worker caches the main shell and its versioned resources only after validation. A home completion marker prevents incomplete main pages being used offline. Online authentication responses take precedence over cached main HTML.
- Existing top-level `/case-manager` entries enter `/?workspace=cases` when the main shell is ready. The main tab host consumes this parameter, selects an existing case tab or creates one, and exposes its original mobile floating navigation. Iframe case pages retain their route. Manifest identity and start URL remain stable.
