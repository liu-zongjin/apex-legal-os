# Six-hour application telemetry persistence

Source recovery point: `6e1ccb1`; branch `codex/admin-six-hour-telemetry-20261021`.
Previous Worker deployment: `c71459b6-9d26-459a-97bb-f03e89aee44b`.

## Behavior

Same installation saves at most once per rolling 21,600 seconds; a new installation
saves immediately. The conditional upsert and sampled daily-activity insert are one
atomic D1 batch, retaining first_seen, the existing schema and response contract.
Repeated legacy minute reports write zero rows, but still consume requests and
indexed D1 reads. Version/OS and daily activity follow saved samples, so brief
cross-midnight activity may be absent from daily counts. Summary `online` retains
its field name with six-hour saved-activity semantics. Dashboard wording explains
sampling and no longer claims real-time operation.

No native timer, installer, release asset, update feed, website collection or public
message behavior was changed. Pending client six-hour interval reminder recorded
in AGENTS.md, PUBLIC_UPDATES_AND_ADMIN.md and user-requested memory extension.

## Checks

- Public-admin 16 tests passed using temporary real Miniflare D1: duplicate row
  writes zero, fresh environments, exact six-hour boundary, concurrent requests
  save once, UTC midnight, first_seen preservation, version sampling and six-hour
  summary cutoff, existing auth, website metrics, downloads, messages and entrance.
- `apex_guard.py extended` passed; existing warnings/skips remain.
- Wrangler deployment dry-run passed.
- Local anonymous browser UI check passed: six-hour label/count/explanation,
  desktop/mobile overflow, existing message publication/preview/withdrawal and
  client polling/privacy behavior. The UI harness now navigates explicit tabs,
  matching the existing three-tab dashboard.
- Screenshots: ignored `.tmp/system-messages-ui/application-six-hour-1440.png`
  and `application-six-hour-390.png`.
- No synthetic telemetry or test announcements sent to production.

## Deployment

Pending Worker-only deployment and authenticated production readback. No D1
migration required. Source branch remains separate from main for owner review.
