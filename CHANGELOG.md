# APEX Changelog

All notable user-visible changes are recorded here. Internal refactors are only
listed when they affect compatibility, reliability, or future maintenance.

## Unreleased

### Fixed

- 移动端系列案件子案主表现在优先显示子案的正式案件名称，不再把纯数字的子案编号误当作标题；编号、阶段、更新时间和案号分别展示，底部悬浮导航也不会遮住末尾卡片。
- Mobile case-management reminder lists now request and render the complete
  online/offline data set instead of collapsing older overdue records behind an
  easily missed disclosure control.
- The mobile efficiency-center panel is constrained to the visible viewport;
  the sidebar logo and empty-tab toolbar title no longer overflow or truncate.
- Reminder Center now renders its latest cache immediately, including a valid
  empty cache, and clearly labels live, pending, and offline-cache states.
- Safari home-screen icons and web-app manifest icons now use the same APEX
  artwork as the desktop application, with versioned asset URLs for refresh.
- Connection indicators now use server health checks plus the local Tailscale
  daemon state rather than browser network events, distinguishing Tailscale,
  LAN, pending, and offline-cache access.
- The mobile Efficiency Center now opens above the bottom bar instead of being
  clipped by it; mobile sidebar controls and section labels keep readable
  contrast in the light theme.
- Home-screen installations now start at the full home workspace and the
  service worker no longer redirects them into Case Management.
- The sidebar now uses the same APEX horizontal wordmark on mobile and desktop
  when no user-selected brand mark is present.

### Added

- Printer Scanner Drive downloads and case/AI exports now show a persistent
  progress panel with phase, elapsed time, transferred size, and an ETA when the
  response size is available, including for small files.
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
