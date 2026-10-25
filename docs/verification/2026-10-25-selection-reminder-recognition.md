# 2026-10-25 selected-text reminder recognition

Implemented in the canonical local source on branch
`feature/selection-ai-reminders-20261025`. Recovery baseline: `df13310`.
No database migration is needed.

## User behavior

- Todo and appeal/objection-period drawers have AI recognition sections supporting
  pasted text, pasted screenshots and PDF/image/text files, using shared notice OCR.
- Selected text has four context-menu actions: hearing, preservation, todo, appeal.
  Each opens a fresh case workspace, prefills the recognition input and starts the
  existing/new recognition request automatically. Other unsaved drawers are retained.
- The host bridge covers same-origin pages, input/textarea selections and dynamically
  nested mail srcdoc frames. Its installed marker belongs to each Document, avoiding
  lost handlers when an initial blank iframe navigates to its actual body.
  The mail viewer retains its original sandbox and script restrictions.
- Recognition only creates a form draft. Existing Save owns database/calendar writes.
  Missing procedural dates/periods remain blank; no legal deadline is inferred.
- Selected text is not stored in URLs, serializable tab state or localStorage.
  As with existing recognition, the selected text is submitted to the configured AI
  service when the user chooses a recognition action.
- Late responses cannot overwrite a different/closed editor. All four recognition
  requests share the three-minute timeout. Notice panels use theme tokens.

## Verification

- `python3 scripts/apex_guard.py extended`: passed; 1,149 tests, 26 skipped.
- `python3 scripts/apex_guard.py fast`: passed after the final theme adjustment;
  20 tests. API snapshot includes two additive recognition routes.
- `python3 -m unittest tests.test_reminder_recognition`: 6 passed, covering extraction,
  literal case matching, hallucinated case IDs, files, empty/oversized input,
  AI fallback, invalid dates, missing times and unsupported recurrence values.
- `python3 tests/reminder_recognition_browser.py`: passed in Chrome against anonymous
  mocked APIs. Covers dynamic nested sandboxed mail selection, automatic navigation
  and all four recognition destinations, editable-input selection, Escape dismissal,
  late-result isolation, plus 1440×900 and 1024×768 light/dark captures.
- Inspected anonymous light and dark screenshots; corrected file-panel background and
  text contrast. Captures are under ignored `.tmp/reminder-recognition-review/`.
- Generated frontend assets rebuilt. `git diff --check` passed.
- Local `/api/server-status` reported running source matching disk and asset version
  2026102503. Unauthenticated POST probes correctly returned 401.

## Limits of verification

Browser/provider responses and OCR upload extraction were mocked. Live provider
quality, actual PDF/image OCR, saving records, iCloud synchronization and execution
inside the installed native WebKit shell were not exercised end-to-end. Cross-origin
remote web pages cannot expose their selection to the same-origin DOM bridge.
The existing hearing/preservation APIs and save paths remain compatible.
