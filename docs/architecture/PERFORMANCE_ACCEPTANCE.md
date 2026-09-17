# APEX Performance Acceptance Baseline

Performance work must preserve the existing single-user, local-first product
contract. A change is accepted only when the extended guard passes and the
affected workflow produces the same persisted records and generated artifacts.

## Anonymous workflow matrix

| Area | Required workflow | State that must survive |
| --- | --- | --- |
| Knowledge | Search, open an article, add a note, return to the list | Query, filters, reading position, note anchor |
| Cases | Open a case and a series case, edit a todo, return from files | Case/subtab selection, table and body scroll |
| Research and AI | Ask a question, inspect citations, reopen the workspace | Conversation, citations, running backend job |
| Documents | Select a client and case, generate and save a document | Form draft, selected records, output bytes |
| Mail and Feishu | Open an account, inspect a message, run manual sync | Account, selected message, sync result |
| Court automation | Read status, run a safe draft step, return to the page | Login/session state, job and draft identifiers |
| Recording and files | Start/stop recording, upload, OCR and download | Active media/upload protection, final artifact |
| Personal and finance | Open protected data and calculate/export | Unlock state, filters, calculation and export |

All fixtures must be fictional and all databases temporary. Live case data,
browser profiles and credentials are never used by automated tests.

## Measurement scenarios

Measure cold start, warm start, five minutes idle, and workspaces containing 1,
5 and 10 mixed tabs. Record the native shell, backend, WebKit and helper process
RSS/CPU separately. Run 60 open/switch/hibernate/restore cycles and fail the
change if memory grows continuously or page state differs after restoration.

Initial budgets are: local API p95 at or below 500 ms; five-tab resident memory
at least 30 percent below the pre-change baseline; idle app-tree CPU at or below
1 percent with optional integrations disabled; and no common interaction more
than 5 percent slower. Hardware, macOS version, fixture revision and enabled
integrations must accompany every recorded comparison.

## Hibernation safety

Only explicitly registered, low-risk pages may hibernate. Editors, recordings,
uploads, CAPTCHA flows and browser automation remain mounted until they expose a
versioned snapshot/restore contract and a positive `can-hibernate` response.
If capture or restore fails, keep the original page resident.
