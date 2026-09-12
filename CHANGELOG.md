# APEX Changelog

All notable user-visible changes are recorded here. Internal refactors are only
listed when they affect compatibility, reliability, or future maintenance.

## Unreleased

### Changed

- 「知识中心」已重构为面向日常使用的入口：默认「今日」聚合当前案件相关知识、最近使用与收藏；「查知识」只展示已核验结论并提供查看原文、复制引用、加入案件研究和带入 AI 的操作；新增每天 8 张的「5 分钟复习」。审核、分类合并与资料失败处理收进右上角「知识治理」，原 `/legal-knowledge` 地址和 `claim_id` 深链接保持兼容。新增第 3 号迁移及学习、复习、使用事件接口，状态失效的结论不会进入日常检索或复习。

- The knowledge-base article reader now gives the main text card slightly wider
  left and right padding without changing its spacing from the outline and notes
  panels. Its smart outline now keeps repeated section labels under each major
  heading, and the highest-level outline entries use a lighter neutral style.

- The home page's tag editor was upgraded into a full “标签与分类管理” dialog
  with three segmented scopes — 全部自定义库, 专业领域, and 作者. Each scope now
  shares the Apple-inspired glass styling (frosted dialog, segmented tabs,
  editable glass rows with drag handles and count pills) and supports drag
  reordering, inline renaming, and deletion. Renaming or deleting a domain or
  author is applied to every article through new `PUT /api/domains/rename`,
  `DELETE /api/domains/{name}`, `PUT /api/authors/rename`, and
  `DELETE /api/authors/{name}` routes; ordering is remembered per scope. The
  sidebar now also honours the saved domain order.

- The global tag-and-category editor is now placed in the top-level 知识库
  header, with the empty 自定义库 state pointing back to that single entry.

- Non-editing sidebar label lists no longer show drag handles or accept
  taxonomy reordering; reordering remains available inside the tag editor.

- The AI enhance page was refined in the same Apple-inspired glass language:
  the panel now uses a translucent frosted surface with a hairline header, the
  model picker, MCP-extensions and strategy-overview controls render as glass
  pills, the history sidebar search and active items gained soft rounded
  surfaces, the suggestion cards are frosted with a hover lift, and the input
  field plus send button use a larger radius with an accent gradient. Every
  non-SVG icon in the page — MCP/Skill check marks, the scope-exit cross, close
  buttons, the folder-scope chevron and add button, file tree folder/file
  glyphs, citation link/file glyphs, source verification check, message delete
  cross, and the history group caret — was replaced with an inline SVG. The
  shortcut hint is now a borderless, muted key line, the history toggle is a
  borderless icon button that tints on hover and rotates when open, the
  file-tree chevron is a thin single-colour SVG, and the model picker’s
  provider columns each scroll independently with sticky group headings.

- The home sidebar's knowledge sections and tag list were refined in the same
  Apple-inspired glass language: section headers, nav items, tag categories and
  tags share consistent 11px-radius pills, selected rows gained a soft accent
  halo, counts render as understated glass pills, the third-level tags now show
  a hairline hierarchy guide, and the footer controls were spaced out. Every
  non-SVG icon in the sidebar — the drag handles, section chevrons, quote
  refresh, tag badge, and author glyph — was replaced with an inline SVG, and
  the drag-to-sort handles are now hidden in normal use, appearing only on
  hover, keyboard focus, or while dragging.

- The 法答网 search page was restyled in a quieter, Apple-inspired glass
  language: an ambient gradient background replaces the full-page red wash, and
  the header/search panel, topic cards, answer cards, sidebar, back-to-top
  control, and AI panel share frosted translucent surfaces, hairline borders,
  soft layered shadows, and rounded pill buttons. Every non-SVG icon — the
  update, AI, refine, restore, expand, notes, close, trash, citation, welcome,
  and status glyphs — was replaced with an inline SVG, and the sidebar section
  chevron is now an SVG data URI. Dark mode and `prefers-reduced-transparency`
  keep the same layout with legible opaque fallbacks.

- The invoice center was restyled in a quieter, Apple-inspired glass language:
  an ambient gradient background, a frosted top bar and filter strip, glass
  field/select controls with a custom APEX chevron, tinted toggles for the file
  types, a segmented tab control, and a rounded glass table card with a sticky
  blurred header and hairline row separators. The empty state now shows a
  frosted receipt badge, links render as filled gradient buttons, and the
  history, automation, preview, and toast surfaces share the same materials.
  Dark mode and `prefers-reduced-transparency` fall back to opaque surfaces for
  legibility. The invoice center's dropdowns (mailbox, quick range, and
  automation fields) now open APEX-styled menus instead of the system menu,
  the scan result no longer leaves the empty-state placeholder above the table,
  and the ZIP download link no longer shows a text underline.

- All APEX default AI workflows—including Q&A, summaries, law-answer
  refinement, research memos, morning briefings, and automated filing—now call
  DeepSeek V4.1 Flash through the `deepseek-flash` gateway model. Existing
  saved V4 Flash selections are automatically migrated to the new model.

- The “一张网” inbox cards were redrawn in a quieter, Apple-inspired glass
  style: cards now use a 16px radius with hairline borders and layered soft
  shadows, delivery and signature states render as tinted pills, and the
  footer actions gained a restrained pill treatment with the primary action
  highlighted. Attachments were rebuilt as frosted liquid-glass document
  tiles with a per-extension badge (PDF keeps the brand tint), quieter
  download/archive buttons, hover lift, reduced-transparency fallback, and
  matching dark-mode surfaces.

- On mobile, a series case's “子案信息主表” now uses the same compact card
  pattern as the ordinary case list while viewing. Each card shows the child
  name, stage, number, update date, and a concise identifier; tapping it opens
  the existing full child-case detail page. “编辑主表” keeps the complete
  field-by-field table for direct editing.

### Fixed

- 修复标签与分类管理：作者/专业领域改名保存不再因分步请求报错，标签组、标签及文章关联现在一次事务提交；同时修复删除后标签复现、未保存草稿被刷新覆盖、计数重复和离线编辑空白等问题。
- 修正待办事项列表中较长事项文本溢出标签列、遮挡提醒时间和剩余时间的问题；长文本现在会在待办列内自动换行。
- 修正移动端系列子案卡片标题字段：优先显示子案正式案件名称，纯数字子案编号仅显示在编号位置。
- Personal-center Touch ID unlock works again in the private deployment. The
  native shell's biometric challenge and session exchange now bypass the access
  login gate, matching the existing Touch ID login bridge; the exchange remains
  protected by the native-shell bridge secret.
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

- “我的笔记”导航计数现在显示笔记条数，而不是有笔记的文章数量。
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
