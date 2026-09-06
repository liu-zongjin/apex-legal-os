# APEX Engineering Rules

These rules apply to Codex, OpenCode, DeepSeek, GLM, and every other agent or
developer changing this repository.

## Before changing code

1. Read `docs/architecture/SYSTEM_MAP.md`, `docs/design/DESIGN_SYSTEM.md`, and
   `docs/architecture/shared-capabilities.json`.
2. Run `python3 scripts/apex_guard.py preflight` and inspect the reported impact.
3. Check `git status`. Preserve unrelated work. Create a checkpoint commit before
   a risky or cross-module change.
4. Search for every consumer of the component, field, route, event, or text being
   changed. A shared change is incomplete until every registered consumer is
   considered.

## Change classification

- A focused change touches one feature and no shared component, API contract,
  database schema, native shell behavior, or global visual token. Run the fast
  checks and the feature tests.
- A cross-module change touches any shared capability, API shape, migration,
  native shell behavior, global CSS/token, or multiple features. Use a separate
  branch, run the extended checks, and review all affected screens.
- Do not mix unrelated cleanup or refactoring into a requested change.

## Compatibility and data safety

- `legal_kb.db`, `uploads/`, `article_images/`, `data/`, browser profiles,
  generated previews, logs, and local secrets are runtime data, never source.
- Tests must use temporary databases and anonymous fixtures. Never point tests or
  migrations at the live database.
- Back up the live database before applying a new numbered migration.
- Additive API changes are preferred. Before removing or renaming a route, field,
  table, CSS variable, DOM event, or page entry, migrate every consumer or keep a
  documented compatibility adapter.
- Do not hard-code credentials. Keep real credentials in ignored local config or
  the macOS Keychain.

## Shared capabilities

- Reuse registered shared components and data adapters. Do not create a second
  implementation that is merely similar.
- When a shared capability changes, update its registry entry and run the tests
  listed there.
- Cross-frame messages use namespaced `apex:*` event names and documented payloads.
- The case-management client archive is the single source of truth for client
  choices. Document generators may adapt its records but must not maintain a
  separate client archive.

## Design and performance

- Preserve APEX's restrained Apple-inspired visual language. Use design tokens;
  do not introduce near-duplicate colors, spacing, radii, shadows, or controls.
- Do not use macOS-native dropdowns, dialogs, alerts, or similar controls inside
  an APEX page. Build or reuse APEX-styled menus, modals, drawers, and feedback
  components so their material, motion, typography, and interaction match the
  rest of the product.
- Reserve glass/blur for navigation, overlays, toolbars, and key containers.
  Dense content uses clear translucent or solid surfaces.
- Keep keyboard access, focus states, reduced motion, reduced transparency,
  light mode, and dark mode working.
- Inactive pages must pause nonessential polling and animation. Avoid unbounded
  DOM lists, concurrent jobs, timers, and in-memory caches.

## Verification and handoff

1. Run `python3 scripts/apex_guard.py fast`; use `extended` for cross-module work.
2. Review the impact report and every affected consumer.
3. Update `CHANGELOG.md` only for user-visible behavior and update architecture
   records only when a contract or decision changed.
4. Report what changed, affected pages, checks run, real workflows not exercised,
   and the Git recovery point.
