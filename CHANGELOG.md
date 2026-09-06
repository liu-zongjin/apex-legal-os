# APEX Changelog

All notable user-visible changes are recorded here. Internal refactors are only
listed when they affect compatibility, reliability, or future maintenance.

## Unreleased

### Added

- An isolated APEX Mobile anonymous-pilot container, fictional starter records,
  and phone-install metadata. It cannot start with normal database filenames or
  external service credentials.
- Repository governance for continuous AI-assisted development, including shared
  capability tracking, API contract checks, visual rules, and performance budgets.
- A shared client picker and client-data adapter across six case and document pages.
- A local performance panel for page counts, iframe counts, long tasks, Python
  memory, slow requests, and API P95 latency.
- Numbered, repeat-safe database migrations with automatic pre-migration backups.
- Automatic recovery when the macOS WebKit content process terminates.
- Anonymous light and dark visual baselines for shared controls.

## Versioning

Stable local releases use tags in the form `apex-YYYY.MM.DD.N`. Database migrations
have independent monotonically increasing identifiers and are never inferred from
the application version.
