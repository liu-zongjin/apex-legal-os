# APEX Changelog

All notable user-visible changes are recorded here. Internal refactors are only
listed when they affect compatibility, reliability, or future maintenance.

## Unreleased

### Fixed

- Switching case-management pages now leaves inactive workspaces without
  background CSS animation, while the active list removes continuous aurora and
  per-row deadline pulses. The retired sidebar pointer-glow effect has been
  removed with its related animation loop, reducing visible stutter when opening
  and changing pages.
- The case-list “全部字段” menu now remains above the sticky table header when
  open, preserving its intended parent-child menu hierarchy. The top refresh
  control now uses the supplied refresh glyph alone, with an accessible label
  retained for assistive technology.
- Opening settings through the configurable “打开设置” shortcut now lands on
  “工作空间”, consistent with the standard Settings entry. The cached client
  script revision was advanced so the new default applies immediately.
- Refreshing an open ordinary-case or series-child detail with Command-R now
  immediately restores that detail from the current-session snapshot while the
  dashboard and latest case data reload in the background. It no longer flashes
  the top-level case list for several seconds before returning to the detail.
- The series-child detail's “主表字段映射” panel now opens above the elevated
  detail drawer and shows an immediate loading state while its main-table fields
  are read, instead of appearing to do nothing.
- OpenCode Go requests and its connection check now identify APEX and provide
  the required stable session header, restoring gateway calls that had begun
  returning HTTP 400.
- Mobile (≤760px): the efficiency-center menu now opens fully on screen as a
  sheet above the bottom tab bar instead of expanding off-screen; it closes when
  tapping outside, and synthesized touch hover no longer auto-closes it.
- Mobile and light-mode sidebar: group titles are readable again; the legacy
  white text rules from the old dark sidebar now use the liquid-glass skin
  variables, so every color theme and dark mode keeps its intended contrast.
- The QQ mail page no longer overlaps its header, folder tabs, and search row
  on narrow screens; opening a mail now presents the detail as a full-screen
  overlay with a back button instead of squeezing both panes into 45vh.
- Mobile connections through Tailscale no longer flip to offline mode on a
  single stalled probe or an unreliable browser offline event: probes are
  double-checked, the home reminder center stays quiet on transient failures,
  and offline state is decided only by repeated probe failures.
- In the series main table (子案信息主表), “详情” now reliably appears above the
  full-screen series workspace instead of being hidden behind it. The action-column
  台账 button opens the same elevated child detail and preserves the child table;
  closing either view returns to that table rather than the top-level case list.

### Added

- Shortcut action choices now derive from every independently openable page
  type. Current work, case, document, communication, and management tools are
  included; future page types are added automatically unless they require a
  specific case, article, or external-link context.
- Series-main-table columns mapped to “联系与备忘” now appear as contacts in
  the “联调/诉讼/仲裁阶段” group rather than creating their own group. In the
  edit view, contact entries in ordinary cases and series children can now be
  dragged between any contact groups and saved in their destination group.
- Series-child “详情” now opens the same full case-detail page used by ordinary
  cases. Its “主表字段映射” workspace lets users select a child-table column and
  a destination detail field without native menus or dialogs; mappings apply to
  every child in that series, persist across sessions, and refresh the open
  detail page immediately. Supported destinations include “其他当事人”, a named
  contact-and-memo card, case memo, case type, stage, case number, and court.
- Storage management now separates regenerable court-service Chromium caches
  from backend code; clearing them preserves sign-in state, preferences,
  downloaded documents, and case data.
- Added the selectable “历史备份文件” category. Existing migration snapshots and
  every future migration-created snapshot are grouped there for manual cleanup.

- Hearing-detail drawer now shows the linked case's "联系与备忘" hub instead of
  the legacy 联系方式 fields. For a series child it lists every cell in the
  child's main table that the contact-recognition rule flags (phone or email),
  each with its iCloud 通讯录 sync button; the drawer keeps the legacy fields
  only as a fallback when the case cannot be loaded. The calendar's 开庭详情
  popup gets the same treatment, and the calendar's series hearing-group popup
  appends each child's recognized contacts under its own entry; 待办/保全/上诉
  popups keep the legacy fields.
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
- The shared client picker now offers a complete, browsable client list with
  incremental paging and visible counters, three predictable sort modes
  (frequent, name, recently updated) with sticky initial-character grouping,
  recent-client shortcuts, match highlighting, a first-character badge, refined
  check/tick indicators, keyboard paging keys, and bottom-aware menu placement.
- The case-detail "客户信息" table now uses the shared client picker instead of
  a separate 12-result lookup, so selecting a client there gets the same
  complete list, sorting, recents, and highlighting as the document pages.
- In series main-table edit mode, holding Command (or Ctrl) and clicking now
  selects multiple non-contiguous cells, and Command+C copies every selected
  cell (contiguous or not) as a tab/newline grid. Selected cells are counted in
  the sheet status bar, and a non-rectangular selection anchors paste at its
  first cell.

### Changed

- Settings now opens on “工作空间” by default, and that category appears first
  in the left-hand list.
- The “系统与支持” diagnostics area now presents compact performance cards,
  a unified status-and-refresh row, and a bounded slow-request list with
  readable paths and durations.
- Settings now uses a restrained three-level structure: category, page, and
  functional section. Redundant navigation subtitles and generic colored
  labels were removed; section titles now state the actual setting scope.
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
