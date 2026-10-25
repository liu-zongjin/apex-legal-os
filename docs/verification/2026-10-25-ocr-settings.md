# OCR configuration and test entry

Scope: local Stella source, no public packaging or release.

- Settings entry directly follows AI API management and opens the registered
  singleton settings tab; closing it returns to settings using the existing flow.
- Default configuration reuses the existing SCNet model key. An explicit OCR-only
  key is stored by the existing private writer, with owner-only permissions and
  atomic replacement. Existing provider keys are preserved. Environment-controlled
  modes/keys cannot be overwritten by the page.
- Test and business parsing share `backend/ocr_service.py`. The test only uploads
  a program-generated sample and requires an explicit button click. It does not
  read business files or invoke a language model. The endpoint is fixed to the
  official SCNet GENERAL API. No settings were changed during live verification.
- Real test with the existing local credential succeeded: sample digits `123456`
  were recognized, HTTP call and parsing completed in approximately 1.3 seconds.
  This confirms one request, not continuing availability or free pricing.
- Tests cover inherited/dedicated configuration, persistence permissions,
  credential masking, same-origin/management checks, bounded retries, malformed
  responses, timeouts, 435/request-ID reporting, no-key/no-network behavior,
  non-overlapping tests and stale result invalidation after credential changes.
- `node tests/ocr_settings_ui.js` (bundled NODE_PATH) passed with a local anonymous
  fixture server. It covers the settings entry, manual test, dedicated/shared save,
  pending drafts during focus refresh, errors, protected settings and 1440/1024/390
  widths in light/dark themes. Screenshots were visually reviewed.
- `python3 scripts/apex_guard.py extended`: passed, 1169 tests, 26 skipped.
  The check includes concurrent unrelated work already present in this checkout;
  this change stages only the OCR implementation and its required asset references.
- No real case-material upload or real credential change was exercised.
