# AI context audit and concurrent conversations — 2026-10-16

Reviewed baseline: `28f148a` (recovery branch `checkpoint/ai-context-before-audit-20261016`).

## Findings fixed

| Finding | User impact | Resolution |
| --- | --- | --- |
| Context inspection adopted a newer chat save lease without reloading messages | A stale window could overwrite another window's newer history | Separate `history_version` from context/generation versions; context drawer never changes chat leases |
| Private turns could be repeated by a later, ordinary AI answer | Private information could indirectly enter cross-chat recall or summary inputs | Propagate `private_context` through derived answers; migration 22 repairs eligible pre-audit taint chains |
| Adding/deleting a memory cleared every conversation summary | Work context and manually corrected summaries disappeared | Independent memory updates retain source-grounded conversation summaries; revision guards still invalidate stale extraction |
| Summary processing required auto-save to be enabled | Turning off automatic memories also silently stopped long-chat summaries | Persist per-job capture permission and separate summarization from durable capture |
| Relevance selection reordered recent messages | Follow-up context could present old answers after newer messages | Restore chronological ordering after selection |
| Invalid model output could be marked complete | The UI reported success while no usable summary was stored | Validate JSON structure and summary payload before committing success |
| Rebuild reran all completed extraction jobs and could lose a running replacement | Unnecessary provider calls or an empty summary after rebuilding | Retry failed work plus the latest turn; generation leases prevent stale workers cancelling queued replacements |
| Legacy browser imports discarded the returned history revision | The first subsequent question could fail optimistic saving | Retain the import's server revision |
| One global loading/controller state locked all AI conversations | No switching/new chats until the current answer completed | Conversation-owned task/controller state, input snapshots and visible-state projection |

## Concurrent conversation behavior

- Up to four simultaneous generations; new conversations and navigation remain available.
- Each request keeps its original model, skill, source scope, question and history key.
- Answers can complete in reverse order without touching another conversation's loading indicator or draft.
- Cancellation targets only the selected conversation. If cancellation is not acknowledged, the UI continues checking the original task rather than claiming it stopped.
- Bounded pending-marker arrays retain compatibility with the old single marker; page recovery does not force a conversation switch.
- Network interruption checks the original server task before creating a replacement answer. Missing/expired server state produces a recoverable error.

## Interface

Shared design tokens provide translucent modal chrome, restrained highlights and shadow, quiet reading surfaces, segmented filters, collapsible source cards and a fixed footer. The memory editor is collapsed until needed so saved memories remain visible. Keyboard focus, 390/1024/1440 widths, light/dark themes and reduced-motion/transparency rules are retained.

## Validation

- Final `apex_guard.py extended`: **881 tests passed**, including isolated database migration, asynchronous races and restart verification.
- `user_memory_ui.js`: CRUD, filters, safe text, settings, errors, focus and responsive light/dark layouts passed.
- `ai_context_ui.js`: provenance, exclusions, summary edit, retry and keyboard behavior passed; verifies that inspection never adopts a chat lease.
- `ai_parallel_chats_ui.js`: switching/new chat during generation, reverse completion, isolated drafts/progress, scoped cancellation, two-task reload recovery, failed cancellation acknowledgement and legacy import revision passed.
- `case_ai_ui_harness.js`: existing case AI scope, navigation, drafts and recovery checks passed.
- Real configured provider (`opencode:deepseek-flash`), anonymous data and an isolated temporary database: extracted an explicit preference with the original message ID; answered using an earlier fictional contract's 80万元 and 2026年10月1日; persisted a source-linked summary and completed the background job. No real client or case material was sent.

Live checks demonstrate the configured provider and these anonymous scenarios; they do not establish the accuracy of every possible legal fact or provider response. Schema migrations retain the application's automatic pre-migration database backup path.

## Restart scripts included after explicit scope confirmation

Reviewed `restart.py` and the desktop `.command` entry. Added authenticated local
status verification without logging or storing credentials. Removed the wrapper's
redundant unauthenticated fixed-port probe, which could contradict verified success;
it now opens the configured port after the helper succeeds. Configuration loading
is bounded, malformed status responses retry safely, and a process exiting before
SIGTERM no longer aborts restart. The failure message directs users to the actual
reported cause rather than always suggesting force-quitting Python.

Eleven anonymous restart tests pass, including a real disposable HTTP Basic Auth
server, old-PID/stale-source rejection, unauthorized responses, malformed data,
configuration timeout and both desktop wrapper success/failure paths. Shell syntax
validation passes. Tests do not stop or restart the live service.
An authenticated read-only status check also confirmed that the running local
service's source fingerprint matched disk after these changes.
