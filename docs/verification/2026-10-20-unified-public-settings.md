# Shared local/public settings and announcements

Date: 2026-10-20 (Asia/Shanghai).
Branch: `codex/unified-public-settings-20261020`.
Recovery checkpoint: `bbc93e1` (parent/main `8acbd15`).

## Scope

- One canonical local/public/PWA home message bell. Public text, no device IDs or
  telemetry consent dependency; foreground five-minute checks and reconnects,
  bounded offline cache, first panel opening clears the current red dot.
- Shared appearance row in the existing app preferences table; new runtime defaults
  are 新用户 and blank law-firm identity/logo. Existing configured local identity
  remains runtime data. Sidebar greeting defaults hidden. Settings update ordinary
  and case-context AI welcomes without resetting conversations.
- The same profile supplies standalone and bundle/case-save DOCX exports and browser
  previews. Firm logo remains independent from app branding, is validated/re-encoded
  and is never filled with the application logo by the public builder. Page/table
  CSS and Word layout remain shared. Standalone powers of attorney also consume
  the shared profile because their export function is shared with document bundles.
- Shared first-entry notices for meeting/approval, explicit original-tool experience
  and one remembered acknowledgment; existing vendor account requirements remain.
- Judicial-message/hearing-notice purpose models are selectable in API management.
  Custom Chat Completions/Responses services have OpenAI/Kimi setup presets, private
  runtime keys, namespaced models and shared request/streaming adapters.

## Review fixes

The user found a blank standalone firm-letter preview while testing. The new
branding interpolation had called a missing escape helper. It is now defined and
all related form/suggestion/tag/contact interpolations safely render literal text.
The actual native Stella window was refreshed and visibly displayed the populated
preview again, without submitting a document or changing case data.

Additional review/verification corrected duplicate document prefixes, a shared
client-picker resize handler passing Window to Node.contains, placement of the
configuration hint inside the form column, unsaved-setting draft loss on foreground
return, stale profile-read races, stale custom model selections after removal,
protocol switching with an existing endpoint suffix, and hearing-recognition API
metadata still reporting the global model instead of its selected purpose model.
Generated bootstrap/lazy assets and versioned source assets were synchronized with
PWA shell 265. No offline cases, pending-operation queues or user caches are cleared.

## Verification

- Extended repository checks: 966 tests passed before the final purpose-metadata
  regression additions; final whole-tree result recorded below after commit.
- Seven isolated appearance/custom-provider tests passed, including actual extracted
  hearing/SMS execution paths using the chosen purpose model and anonymous data.
- Worker/Pages gateway: 11 tests passed with local Miniflare D1, auth/origin checks,
  message bounds, public active-only feed and withdrawal behavior.
- Three isolated browser suites passed. Actual four generator pages at 1440/1024,
  light/dark: blank/custom branding, safe literal inputs and live firm-letter preview.
  Settings/API/notice flows: username and case-context synchronization, draft
  preservation, OpenAI/Kimi presets, custom models, purpose selection, removal and
  shared notice opt-out. Message tests include first-open read persistence, offline
  cache, withdrawal synchronization, hidden-page pause and keyboard modal behavior.
- Public source snapshot checks compare shared message/profile assets byte for byte
  and confirm no law-firm/app logo is copied into the firm-logo slot.

Production D1 was exported to an owner-only ignored file before additive
`0002_messages.sql`, which applied successfully. Worker deployment
`6203633b-5d59-4f3d-b31f-3c61ebeaef27` made the authenticated announcement UI and
public feed available through the existing Pages Service Binding. Live HTTPS checks
passed for public empty feed, CORS, protected history rejection, normal login,
protected UI/script/history, wrong-origin publication rejection and logout. No
production announcement or fake installation was created. A final asset-only
accessibility adjustment is deployed and recorded below.

No public installer/feed was published or replaced. Installer freeze, macOS 12.0
WebKit execution, real vendor credentials/billed model calls and Sparkle GUI
install/relaunch are not claimed by these browser/transport/snapshot checks. AI
protocols were exercised with mocked responses; live case data was not used for
any automated test. Existing application configuration and records remain outside
Git and the public snapshot.
