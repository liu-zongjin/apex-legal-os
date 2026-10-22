# APEX Engineering Rules

These rules apply to Codex, OpenCode, DeepSeek, GLM, and every other agent or
developer changing this repository.

## Fixed local development and public release policy

User-confirmed policy (2026-10-20); applies to every future Stella iteration.

- All feature iteration, optimization, debugging and testing default to the canonical
  local Stella project and take effect locally for the user to test. Maintain one
  source implementation; do not maintain a separate evolving public edition.
- Local and public Mac builds share feature implementations and entry points,
  including the native update menu. The user-confirmed exception (2026-10-22) is
  that public builds may omit Personal Center and its family-finance sync.
  Otherwise privacy sanitization removes user data/defaults, not features.
  Source-connected update checks must preserve the canonical source connection,
  identity and runtime: never install a public binary over that shell if doing
  so would switch its data directory or disconnect local iteration.
- Committing/merging source or updating website feature notes does not authorize
  building or publishing a public installer, update archive, delta or appcast.
  Only do those release actions when the user explicitly instructs packaging and
  publication after local testing. This policy update itself authorizes no release.
- At an authorized release, use the latest locally tested version, including all
  intended completed changes. Review and commit that exact source before freezing
  Git HEAD; do not accidentally build an older branch or omit tested local edits.
  Record the source revision and release version/build.
- Public full installers and incremental updates must contain no developer/local
  user data: prefilled court-network phone numbers/accounts, team lawyer identities,
  clients, opposing parties, cases, contacts, attachments, generated documents,
  databases, runtime directories, browser sessions/storage, credentials, tokens,
  personal settings, or identifying fixtures/defaults embedded in source/assets.
  An allowlist of source files alone is insufficient: also audit embedded defaults
  and the final artifact. Use empty initialization or demonstrably fictional data.
- Build in an isolated staging directory. Never clear or modify the developer's
  live data to obtain a clean package. Preserve shared functionality and layout;
  initialization and removal of private defaults must not become a second product.
- Deltas are generated only between exact previously published sanitized archives
  and the new sanitized archive, never from the developer's runtime/data directory.
  Preserve recipients' existing local data and settings during updates. Keep the
  full archive fallback when an eligible delta cannot be generated.
- Before publication verify the final artifact is free of local user data and
  verify clean first launch plus update/data preservation using temporary anonymous
  profiles. If privacy checks fail, fix them before publishing.

## Pending next public release reminder (2026-10-21)

Before the next explicitly authorized installer release, remind the user to change
all shipping client telemetry reporting intervals from 60 seconds to six hours
(21,600 seconds), retaining an immediate first consented report. The cloud backend
already limits persistence to one save per installation per rolling six hours;
existing installers still send every minute. Track completion in
`docs/PUBLIC_UPDATES_AND_ADMIN.md`. This reminder authorizes no installer release.

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
  checks and the feature tests. After they pass, create one clear commit and
  push it to `origin/main`.
- A cross-module change touches any shared capability, API shape, migration,
  native shell behavior, global CSS/token, or multiple features. Use a separate
  branch, run the extended checks, review all affected screens, and push the
  branch to GitHub. Do not merge it into `main` until the user has confirmed the
  relevant pages or behavior.
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
- Do not use system- or browser-native dropdowns, dialogs, alerts, or similar
  controls inside an APEX page, including unstyled native HTML controls. Build
  or reuse APEX-styled menus, modals, drawers, and feedback components so their
  material, motion, typography, and interaction match the rest of the product.
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
