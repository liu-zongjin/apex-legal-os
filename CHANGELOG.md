# APEX Changelog

All notable user-visible changes are recorded here. Internal refactors are only
listed when they affect compatibility, reliability, or future maintenance.

## Unreleased

### Fixed

- OpenCode Go requests and its connection check now identify APEX and provide
  the required stable session header, restoring gateway calls that had begun
  returning HTTP 400.

### Added

- Hearing-detail drawer now shows the linked case's "联系与备忘" hub instead of
  the legacy 联系方式 fields. For a series child it lists every cell in the
  child's main table that the contact-recognition rule flags (phone or email),
  each with its iCloud 通讯录 sync button; the drawer keeps the legacy fields
  only as a fallback when the case cannot be loaded. The calendar's 开庭详情
  popup gets the same treatment, and the calendar's series hearing-group popup
  appends each child's recognized contacts under its own entry; 待办/保全/上诉
  popups keep the legacy fields.
- Repository governance for continuous AI-assisted development, including shared
  capability tracking, API contract checks, visual rules, and performance budgets.
- A shared client picker and client-data adapter across six case and document pages.
- A local performance panel for page counts, iframe counts, long tasks, Python
  memory, slow requests, and API P95 latency.
- Numbered, repeat-safe database migrations with automatic pre-migration backups.
- Automatic recovery when the macOS WebKit content process terminates.
- Anonymous light and dark visual baselines for shared controls.
- The shared client picker now offers a complete, browsable client list with
  incremental paging and visible counters, three predictable sort modes
  (frequent, name, recently updated) with sticky initial-character grouping,
  recent-client shortcuts, match highlighting, a first-character badge, refined
  check/tick indicators, keyboard paging keys, and bottom-aware menu placement.
- The case-detail "客户信息" table now uses the shared client picker instead of
  a separate 12-result lookup, so selecting a client there gets the same
  complete list, sorting, recents, and highlighting as the document pages.

### Changed

- Client picker menus across all case and document pages adopt the shared
  design tokens for surfaces, motion, and focus states in light and dark mode.
- Client picker menus are now anchored to the viewport (fixed positioning with
  a body portal, like the shared date picker) instead of living inside scrollable
  drawers and forms. They can no longer be clipped by container boundaries, they
  flip above the input when space below is tight, and scrolling the page no
  longer fights with scrolling the list.

## Versioning

Stable local releases use tags in the form `apex-YYYY.MM.DD.N`. Database migrations
have independent monotonically increasing identifiers and are never inferred from
the application version.
