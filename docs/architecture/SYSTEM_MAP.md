# APEX System Map

## Runtime

APEX is a single-user hybrid macOS application distributed as `dist/Stella.app`. The AppKit shell
containing one WKWebView. It loads the local FastAPI service at
`http://localhost:8000`. The Python service owns business logic, SQLite access,
file processing, AI integrations, scheduled work, and browser automation.

The optional anonymous mobile pilot is a separate Docker runtime. It serves the
same FastAPI and web assets with a separate, fictional SQLite database and has no
connection to the Mac application's data directory. Its container entry point is
`scripts/mobile_pilot_entrypoint.py`; see `APEX_MOBILE_CLOUD_PILOT.md`.

```text
Stella.app (AppKit)
  └─ WKWebView
       ├─ frontend/index.html + app.js + style.css
       ├─ feature pages loaded as same-origin iframes
       └─ HTTP / postMessage / native message handlers
              ↕
        FastAPI backend
          ├─ legal_kb.db
          ├─ uploads and case folders
          ├─ AI, mail, Feishu, Quark and legal-data integrations
          └─ court browser automation and background schedulers
```

## Ownership boundaries

- `native-shell/`: window lifecycle, macOS menus and shortcuts, notifications,
  permissions, downloads, clipboard, biometric bridge, and WebKit recovery.
- `frontend/`: presentation and browser-side interaction. Shared browser assets
  use the `apex-*.js` / `apex-*.css` prefix.
- `backend/`: APIs, persistence, integrations, document generation, and workers.
- `tests/`: isolated tests using temporary or in-memory data.
- `scripts/`: maintenance, preflight, contract, release, and diagnostic tooling.

Runtime data and credentials remain outside version control even when physically
located inside the project directory. See `.gitignore` and `AGENTS.md`.
`LEGAL_KB_RUNTIME_DIR` may redirect the database, uploads, and article images to
an isolated runtime directory; the local app defaults to its existing base
directory.

## iPhone offline shell

The Home Screen entry `/case-manager` is a public, data-free application shell.
Its versioned CSS/JavaScript and Service Worker are public so an expired session
cannot prevent repair or upgrade; every case API and offline-snapshot API remains
authenticated. `GET /api/pwa/session-status` exposes only reachability,
authentication state, and the shell version.

The Service Worker validates the shell version header and content type before a
staged cache becomes active. Navigation is cache-first and keeps one previously
verified release for rollback. Case snapshots continue to use the existing
`legal-kb-case-manager` IndexedDB database, while pending case mutations retain
their existing localStorage queue. Shell repair may remove shell caches and the
worker registration, but must never remove either user-data store.

Legacy top-level case entries enter the existing main tab host at /?workspace=cases
and reuse its mobile floating navigation. Case iframes are never redirected.
The worker prepares the main
page and its required assets from public data-free /app-shell and static assets.
Installation requires a complete main shell even in a fresh standalone store.
Manifest identity remains /case-manager, but new installations start at /. Legacy
standalone case HTML redirects to the main host before app startup; iframe HTML
does not redirect. Expired case iframe authentication opens login in the parent. It never
caches login HTML. Offline root navigation uses a separate completion marker;
online root navigation still respects login responses. No business API becomes
public and no cached user data is deleted during this upgrade.

## Page activity and overview visibility

`apex-page-lifecycle.js` derives activity from two independent inputs: the host
tab selection and document visibility. Backgrounding must not overwrite the host
selection; returning to the foreground resumes selected pages and their timers.
Unselected iframes remain paused. Overview cards use visible base styles with no
entry animation, so suspended or cancelled animations cannot hide navigation.
Shell v245 refreshes these assets while retaining offline records and drafts.

## Stability boundaries

- FastAPI route method, path, request parameters, and documented response fields
  form the browser/backend contract.
- The Efficiency Center preference endpoint keeps its existing `order` list and
  optionally stores per-entry `groups` and `subtitles` maps. Older order-only
  clients remain supported; all three values are saved in one SQLite transaction.
- Shared component options and emitted `apex:*` events form the page/component
  contract.
- Active-case menus share `apex-case-picker.js` and its CSS. Popup and inline
  hosts keep their own selection actions; the component owns browsing, keyboard
  navigation, recent selections, client grouping, and full series-child names.
  `GET /api/case-manager/case-lookup` supports bounded offset pagination;
  `items` remains compatible, and `has_more`, `next_offset`, and `folder_bound`
  are additive. Every active series child remains selectable by its original ID.
- Native message-handler names and cross-frame message names form the WebKit
  bridge contract.
- When the disk source changes, the backend returns 503 until the service reloads.
  Browser navigations receive a self-recovering waiting page; API callers retain
  JSON status. The native shell also intercepts local main-frame 503 responses
  and reloads only after `/api/server-status` reports current source.
- Knowledge center `apex:knowledge-prefill-ask` messages carry version 1 and a
  question. The parent accepts them only from a knowledge center tab iframe.
- SQLite changes go through `backend/migrations.py`; startup schema helpers may
  remain during gradual migration but may not introduce new unnumbered changes.
- The knowledge article editor saves title, HTML body, and per-article margins
  through `PUT /api/articles/{id}/editor` in one transaction. The request includes
  the original title and body for conflict detection. `GET /api/articles/{id}/editor-layout`
  loads margins; legacy title and content routes remain available to other clients.
- Article deletion uses `article_trash` snapshots rather than a permanent first
  delete. `DELETE /api/articles/{id}` and `DELETE /api/articles/bulk` preserve the
  article and cascading rows for 30 days; trash list, restore, and purge APIs
  manage those snapshots. An hourly backend task removes expired snapshots,
  including immediately after service startup. Original uploaded files are not
  removed by article-trash cleanup.
- Knowledge classification keeps `articles.domains` as the compatible top-level
  field. Numbered migrations 12-13 add approved two-level taxonomy nodes, per-article
  child choices and exclusions, a durable classification queue, suggestion evidence,
  and persistent child ordering. Article inserts and title/body edits enqueue
  classification; migration 13 queues historical articles once. Rules propose
  concrete child topics from titles and summaries, with configured AI used when
  the rules cannot identify an existing or proposed child. Suggestions need user
  approval before joining the catalog. Migration 16 supplements historical child-topic
  suggestions for previously uncovered domains without changing article choices.
  AI fallback checks coverage for each identified root and retains rule matches. `GET /api/domains`
  adds child nodes and counts without removing legacy `domain` and `count` fields;
  `GET /api/articles` accepts optional `subcategory_id` and classification status,
  while `GET /api/domains/pending-count` drives the visible review queue. Manual choices are
  retained across reclassification. Approving a category queues affected historical articles for automatic reclassification.
  Optional manual reclassification previews actual root and child assignment differences
  and applies only changed articles in batches, preserving manual choices and exclusions. The category-management modal also links
  to the existing custom-tag ordering editor and offers persisted child ordering.
  The review UI pages large suggestion sets through
  `GET /api/domains/suggestions/page` with search and filter parameters; the
  original array-returning suggestions route remains available to older clients.
- Case archive assignments, saved checklist snapshots, and export history are
  kept in SQLite by `backend/case_archive.py`; the bound local case folder
  remains the material source of truth. Saving a checklist does not generate an
  electronic case file. Each export is a separate version under `APEX案卷归档`
  and never changes case status.
- The archive workbench embeds the existing `/case-files` page in an archive picker
  mode. Its file columns, sorting, search, selection, and preview remain owned
  by that page; same-origin `apex:archive-*` messages carry selected relative
  paths and status updates to the archive page.
- Aggregate runtime metrics live only in process memory. The settings performance
  panel never records request bodies, query strings, client names, or file paths.
- Private Mac backup management uses `GET /api/backup-management`,
  `PUT /api/backup-management/settings`, and
  `DELETE /api/backup-management/files/{category}/{name}`. Settings live in
  `LegalKBBackups/backup-settings.json`; the schedule updates the existing
  launchd agent. File deletion accepts only generated names directly inside the
  configured database or uploads backup directory.

## Online reading downloads

`backend/court_dossiers.py` owns `/api/case-manager/court-online/readings`
and `/api/case-manager/court-online/downloads`. Numbered migration 17 stores
account-scoped reading records, jobs, and file state. Session headers and output
directories come from the existing court integration; signed download URLs stay
in memory and are resolved again before continuing a job. Cookie/Authorization
headers are sent only to the court origin, not to OSS file hosts.

One job executes at a time with up to three streaming transfers. Partial files
use validated Range/If-Range or restart when unsupported. Startup recovery pauses
interrupted jobs; account switching pauses jobs before replacing the session.
ZIP64 creation runs off the event loop, preserves original files and order, and
includes a manifest. Partial success is visibly distinct from complete success.
The independent `/court-online-downloads` page uses the shared lifecycle and only
polls while active. Application-material test tasks use the same executor but a
separate labeled source, with no application documents in dossier downloads.

The current account has no effective open dossiers. Directory-tree parsing has
fixture coverage; independent viewer integrations remain pending a permitted
sample. If the normal directory contains no downloadable files, show a clear
notice and direct the user to the official viewer rather than claiming success.

## Change flow

Focused changes run the fast guard. Changes to a boundary above are cross-module:
generate an impact report, update compatibility documentation, run the extended
guard, and inspect every registered consumer.

## AI gateway protocols

CC2API Claude Code-only key groups use the official Claude Code headless client,
installed at the pinned version with `scripts/install_cc2api_runtime.py` into
ignored `data/cc2api-runtime`. `backend/cc2api_bridge.py` passes credentials only
in the child environment, derives the base URL from the configured Messages URL,
and normalizes the client's JSON result into the existing choices contract.
Each call uses temporary configuration, bare mode, disabled built-in/MCP tools,
no session persistence and nonessential traffic disabled. Timeout and cancellation
terminate the child process. Conversation history and system instructions are
passed explicitly; no unrelated project or user configuration is loaded.
The gateway catalog is distinct from official model availability. Client output
limits use Claude Code's token environment setting (minimum 256); temperature
is managed by the official client rather than exposed as a gateway parameter.

## Case AI management

Efficiency Center places 案件 AI 管理 below AI增强. The CASE_AI tab mounts the
existing AI chat panel and saves a separate `ask_history_case_database` history.
`POST /api/ask` with `source_mode=case_database` returns before KB/MCP/skill routing.
`backend/case_ai.py` discovers case-management, case-archive and case-linked tables,
including case-linked research_projects and their ledgers, memo entries, notes and research memos,
plus all synced 一张网 records, filing audits, hearings, deliveries, messages,
attachments and original JSON fields. Model-planned read queries run on one SQLite
snapshot through a restrictive authorizer, with bounded rows, text and execution
time. Aggregation scans all matching records; truncated details require pagination.
Authentication settings and secret columns are excluded. Answers include database
query evidence and snapshot time, distinguish sync dates from real-time portal
state, and link sources back to case management or 一张网. No schema change.

## Saved user memories

Numbered migration 18 adds `user_memories` and singleton `user_memory_settings`.
The authenticated `/api/user-memory` CRUD routes and `/settings` persist local
profile/preferences independently of conversation history. The AI toolbar offers
management and an additive `memory_enabled=false` per-request opt-out. All main AI
workspace sources (including case AI and selected files) use the same bounded
profile context. Saved text is untrusted personalization data, never legal evidence.
Only current short name/preference statements are automatically captured after a
successful answer; explicit anchored chat commands can save/list/delete a record
without a model call. No historical chat, answer, case file or webpage is mined.
Revision checks prevent pending requests from restoring a memory after user
management changes. Global disable retains records while suspending read/capture.
The automatic migration backup runs before schema changes.

## Judicial SMS document download progress

The existing download POST remains synchronous and adds a `progress` result.
`GET /api/case-manager/judicial-messages/{message_id}/documents/{document_id}/download-progress`
returns authenticated, request-local byte counters, current filename, successful/failed
file counts and terminal state. HTTP streams update actual decoded bytes; unknown
lengths remain indeterminate. No URLs, tokens or contents are stored in progress.
At most 64 snapshots are kept in memory, evicting finished entries; duplicate
downloads for the same document return 409. Restart clears snapshots. The case
manager polls serially every 600 ms only during a download with a visible detail
drawer and active page, and stops after completion or when hidden. Final results
distinguish complete success, partial failure, failure and required page action.

## Unified downloads and native delivery

`backend/download_center.py` owns authenticated download-center APIs and atomic JSON
metadata under the runtime `data/download-center` directory. No numbered schema
change is required. Generated exports are streamed through an explicit opt-in
`ApexDownloads.fetch` adapter, staged under server-owned IDs and then delivered by
the existing browser/native save flow. File-upload and in-memory export paths keep
a 500 MiB bound; native delivery of already-generated dossier ZIPs remains streamed
and retains its prior large-file capability. Server-assigned records retain
source, purpose, confirmed case, actual path, byte/file counters and terminal state.
Legacy browser history imports once by stable digest; only exact existing Downloads
basenames are located. Historical judicial documents and dossier jobs are adapted
from their original tables with source and case context, never guessed from names.

Mailbox jobs explicitly separate invoice, case and other attachments. Case jobs
validate the chosen binding before dispatch and again at write, reusing
`store_case_file` with `#邮箱案件材料`; generic confirmed copies use `#下载材料`.
Failed case writes retain staged files and expose partial failure. Ordinary legacy
mail attachment collection now uses its own attachment directory; invoice scanning
retains its invoice directories. Managed mail/court jobs survive page closure,
run at most three concurrently, and restore as interrupted after server restart.
Client-side jobs report page closure as interrupted; inactive pages pause polling.

Native `WKDownload.progress` observations route byte updates to the same-origin
originating frame. A captured record ID allows updates through the parent after a
source frame closes. Final save-panel paths are accepted only after the server
compares the candidate with a known managed artifact using streamed hashes.
This provides accurate Finder locations for user-selected directories without
an API that accepts arbitrary readable file paths. Existing download routes and
case file indexing remain intact. Cleaning completed display history never removes
files, active jobs or unassigned/pending case materials.
## Judicial delivery archive folder

Judicial SMS and court-online attachments share `#Stella电子送达归档`.
Folder creation and legacy APEX/court-document migration apply the macOS Important
red tag to the folder only, preserving other tags. Binding reads migrate legacy
folders without overwriting collisions and update stored file paths. Existing
Stella folders retain later user tag edits; unsupported volumes may archive
without Finder tags.

## Matter local shortcuts

Numbered migration 20 stores per-reminder local paths in `case_manager_matter_local_links`,
with exclusive foreign keys to todos, hearings, preservations or appeals and cascading
metadata deletion. Authenticated `/api/case-manager/matters/{matter_kind}/{item_id}/local-links`
list/add/remove/select/open APIs keep case folder bindings independent. Local desktop
access requires a loopback peer and target, local Origin when present, and no proxy
forwarding headers. Authenticated localhost sessions work in private mode; remote
and proxied sessions cannot open paths on the host. Authentication remains in the
existing middleware. Case API 403 errors retain their permission detail; only 401
or actual login HTML triggers authentication navigation.
Selection uses the existing macOS osascript picker pattern; opening uses argv without
a shell and validates existence and saved kind. Only metadata is removed on unbind.

## Mail team labels

Authenticated `GET/PUT /api/qq-mail/team-labels` reads members directly from
`suohan_lawyers`, the document generator's existing library. Atomic JSON under
the runtime `data/mail-team-labels` directory stores one member per email, scoped
by account, folder and UID with date/from/subject identity checks. Labels survive
summary-cache eviction; missing or invalid persistence fails visibly. Bulk writes
validate all member IDs and cached summaries before saving. Removed members keep
previous labels for filtering; rename uses current member names. This is local
Stella metadata, not mailbox-server flags or synchronization across installations.
The UI filters the loaded summary set (up to 300), alongside existing search,
unread and language filters; changing filters clears selections.

## Authentication errors

The local access middleware marks rejected API requests with
`X-Apex-Auth-Required: local`. The case API adapter redirects the parent to login
only for this marker, legacy plain local authentication responses, or local login
HTML. Integration JSON 401 responses and business 4xx remain feature errors and
never enter the offline fallback. The public session-status probe still detects
actual session expiry. Loopback trust and remote authentication are unchanged.

## Invoice scan coverage

All three mailbox accounts scan selectable IMAP folders, including custom folders,
using read-only selection and BODY.PEEK. Folder names remain server-encoded; folder
hashes isolate UID caches and stored files. Lightweight headers include sender and
date. Generic file names reach content parsing, ZIP entries are bounded and read
without extracting paths, and attachment discovery does not suppress body links.
Link URL hashes prevent same-name collisions. Failed BODYSTRUCTURE reads remain
retryable. The scan cache records remaining UIDs and prior rows for the same date,
format and keyword selection; repeat scans prioritize remaining messages and
folders, retaining completed-folder results so failed links cannot starve later folders.
The existing invoice response adds folder counters and mailbox provenance. Warnings
propagate to download registration and monthly collection as partial completion;
a partial monthly result never advances its successful last_period.

Invoice link resolution unwraps the known Nuonuo QR-generator `content` parameter
before discovery/deduplication and when loading existing scan caches. Vpiaotong
public receipt routes use their read-only invoice information and electronic-file
endpoints, selecting PDF/OFD/XML according to the requested formats. Linked ZIPs
reuse bounded attachment ZIP parsing and retain every selected member. Downloaded
file signatures are checked so an HTML error page cannot masquerade as an invoice.
No browser session, user credential, or external JavaScript execution is required.

## Invoice audit consistency

Invoice scans serialize each account through a reentrant lock before their deadline
starts. Complete date-range UID searches are consumed in bounded passes; completed
and remaining UIDs are retained with each selection and parser version. Metadata
fetches stop at the same deadline. Invoice summaries use their own folder-scoped
cache and do not replace mail-list attachment summaries. Version 2 mail-summary
writes also replace legacy invoice-generated attachment entries with fresh original
mail summaries on their next mail-list load; valid new hashed filenames stay cached. Scan JSON writes replace
atomically; UIDVALIDITY changes reset summary/scan state and write to a new storage
epoch, preserving files from the previous mailbox generation. Metadata caches use
nanosecond file times and a parser version.

Rows add invoice_number and invoice_code from structured fields or invoice text/names. Default
selection and totals group explicit invoice identities; unidentified files remain
distinct by folder, UID and basename. Credit amounts retain their sign and decimal
rounding. New ordinary documents are parsed in staging and not retained as invoices.
Unknown attachment names can be inferred for document MIME types in invoice scanning
only; failed ZIP members do not discard sibling files. ZIP/XML/OFD parsing shares
bounded archive checks. Single-invoice tabular CSVs map header names to their data
row; explicitly named invoice images reuse the existing local macOS Vision OCR
engine. A labelled RMB capital total can recover a rotated/unreadable numeric total.
Ordinary agreements and court documents discussing payments are not invoice evidence.

The existing invoice download API builds all selected files in a worker (at most
5000 files / 250 MiB), validates the selected account's root, and assigns collision-free
ZIP member names. Export history read/repair/write uses one lock and atomic files.
Keys use invoice number plus format, or streamed content hashes for unidentified
files; migrated histories retain legacy aliases. Browser requests carry view/request
revisions so an old account cannot replace current results, selection or histories.

Monthly automation resumes up to 12 bounded passes per execution. Incomplete or
failed collections remain eligible after a 15-minute backoff; successful periods
are skipped, and missed due dates catch up. Existing archives and history persist.

## Case fact-check and evidence-book workflows

`backend/case_workflows.py` owns the additive `/case-workflows` workbench and
`/api/case-workflows/cases/{case_id}/tasks` APIs. Existing case rows and folder
bindings remain authoritative. Durable task metadata and unique output versions
are atomic JSON/files under the bound folder's `Stella办案成果/<task_id>`; no
database migration or live-data rewrite is introduced. Sources carry SHA-256
snapshots and verified private input copies; fixed parsed candidates are hash-checked on resume. Changed originals block continuation, source retrieval and review export.

Fact checking parses every selected file, retrieves bounded candidates for every
draft sentence, validates literal model quotes against those candidates, and
delivers Word/Excel/Markdown plus a JSON audit sheet. AI support/contradiction
labels are preliminary; lawyer review is separate, revision-checked and creates
new immutable files. Scanned PDF pages require explicit cloud-OCR consent; empty
OCR pages and incomplete model responses fail visibly rather than silently
omitting claims. Candidate retrieval is not proof of exhaustive semantic recall.

Evidence books require an ordered, user-confirmed title/purpose list. They share
PDF/image insertion through `backend/pdf_assembly.py` with existing case archive
exports, flatten visible annotations/widgets in a private copy (PyMuPDF >=1.24.2), then add footer space to the compiled copy, bookmarks, independent
Word/Excel catalogs and original-to-compiled page ranges. Original files and case
status stay unchanged. Word conversion uses the existing archive converter.

Jobs retain checkpoints, cancellation and recovery after process restart; one
heavy worker runs at a time. Cancelled synchronous conversions may finish only
in unpublished staging, never register a downloadable artifact. Task/artifact
identity is independent of display filenames. Previous export revisions remain
downloadable. The workbench reuses the registered case picker and file browser.
Its picker messages are version-1 `apex:workflow-status`, `-assign`, `-selection`,
`-clear-selection` and `-picker-ready` (same caseId/paths/itemCode shape as archive
picker messages). Host opening uses `apex:open-case-workflows`, accepted only from
a case-manager frame; case changes use `apex:case-workflow-case-selected` from the
registered workflow frame. Hidden pages pause bounded serial polling.

### Document-led planning upgrade

`backend/evidence_planning.py` normalizes one-to-many evidence/material relationships,
physical page ranges and document item IDs. `evidence_plan` jobs require a legal
document (pasted text or a verified original) and candidate materials; reuse the
fact-check engine and distinguish facts, legal positions, requests and opinions.
Each item retains document paragraph/item or parsed PDF page location. A completed
reviewed fact task can seed a plan only when document text and material hashes match;
its review notes/statuses and source revision are retained.

Plans draft titles, objective summaries and proof purposes from bounded excerpts,
require literal summary references, and retain unassociated documents and unsupported
claims visibly. Suggestions are never certified semantic proof. Lawyer edits include
summary, proof purpose, optional origin/group, linked document IDs and multiple
materials with source page selections. `PUT .../plan` persists optimistic-revision
versions; compilation accepts the fixed plan/revision and checks input fingerprints.
Missing/contradictory links or selected pages that omit cited proof require explicit
acknowledgement; this does not turn the gap into a supported fact.

Books include synchronized Word/Excel catalogs, compiled PDF bookmarks, exact
selected-source-page to compiled-page mapping, and an internal document/evidence
sheet. Legacy one-file entries remain accepted. Task-scoped `material-info`,
`material-preview` and `material-page` provide actual converted page counts and
page-image reading without relying on a browser PDF viewer. No database migration.

## Scanner case imports

`POST /api/scanner-inbox/import` keeps its existing case response and writes PDF
files through `store_case_file` with category `download_material` under the bound
case folder/`#下载材料`. It registers source metadata in `case_manager_files`,
checks folder availability and duplicate imports before contacting the printer,
and revalidates the binding at each write. The scanner page shows save progress
and the destination after completion. Device originals remain read-only.

### Case fact timeline

`backend/case_timeline.py` provides literal-citation validation, date precision, review normalization and deterministic chronological exports. `timeline` jobs reuse workflow material snapshots and parsed-source hashes, process every chunk in checkpointed batches, and optionally compare a reference legal document using the existing fact-check engine. Sorting bounds for month/year/ranges are internal only; unknown and relative dates are not inferred. Date differences and duplicate candidates require human review.

Additive task routes `PUT .../timeline`, `GET .../timeline-source`, and `GET .../timeline-fragments` retain case scope and original hash checks. Reviews use optimistic revisions and immutable version folders. Manual additions must cite a literal fragment from the fixed task cache. Outputs include reviewed event tables and neutral numbered SVG/PDF chronologies; event spacing does not represent elapsed time. The host keeps its existing tab and opening event identifiers while its entry label now names timeline capability.

### Timeline export presentation

`backend/timeline_presentation.py` normalizes `export_options` (`style`: axis/table/cards; `include_evidence`: boolean) and shares visible-event selection, deduplicated sources and visual rendering across previews and exports. The timeline review PUT accepts options additively, retains immutable output revisions and rechecks originals. `GET .../timeline-preview` accepts a saved revision plus presentation options, validates case/task scope and source hashes, renders the first eight included events to escaped SVG, and never writes artifacts or invokes a model.

Word references are native OOXML endnotes, with decimal numbering, internal bookmarks and NOTEREF fields for shared citations. Hidden evidence removes reference marks and the endnotes part from Word and source sections from visual/Markdown/Excel delivery. Source positions that are not verified are omitted from formal notes; the workbench and JSON audit retain original citations and limitations. Review states and excluded records remain in the audit, while formal delivery contains included event text without review columns. Layout options apply to Word/PDF/SVG; Excel remains a fact table. PDF pagination uses existing PyMuPDF Story; no new runtime dependency or schema migration.

## AI generated files

Direct AI instructions request complete fenced files for drawing and file creation.
`backend/ai_artifacts.py` validates bounded text artifacts (eight files, 256 KiB each);
SVG XML and JSON must parse, HTML must be a complete document. Descriptors are derived
from the persisted answer, including legacy code blocks, so there is no new storage
or migration. The message export API adds `artifact_index` and returns original file
bytes or the existing Word conversion for text artifacts. The AI workspace uses the
existing unified downloads flow for delivery. HTML/SVG previews are isolated in
sandboxed frames with restrictive CSP and active/navigation elements removed.
Generated content is never executed on the host. This channel has no raster image
generation service; SVG drawing is available without claiming native image synthesis.


### Case-related knowledge (2026-10-15)

`backend/case_knowledge.py` owns local article retrieval, grounded topic extraction,
per-article usefulness assessment and report generation for the additive
`knowledge_match` task kind. The injected ArticleRepository reuses the article FTS
helper with a complementary escaped LIKE ranking, interleaved and deduplicated even when FTS has hits. At most 48 grounded topics are retrieved against; further proposed topics are counted visibly. At most 120 unique candidates are retrieved,
40 substantive bodies are assessed and 20 recommendations are delivered (10 shown
initially). Insufficient bodies, excluded candidates and failed assessments remain
visible in coverage/audit data. No external search or legal currency check occurs.

The workflow processes selected case chunks in checkpointed batches. Article
body fingerprints and analyzed fragments are saved once in a hash-checked task snapshot;
recommendations require literal quotes on both the article and case side. Per-article assessment prioritizes up to six article-matched issues and twelve case chunks; analyzed issue/source IDs are retained in the audit, including failed candidates. Requests
may contain only pasted document text, only files or both. Optional position, focus
and modified research questions are untrusted instructions for the research task,
not facts. Current article identity/content is compared when opening its snapshot;
changed/deleted articles retain their historical analyzed context.

`GET .../tasks/{job_id}/knowledge-articles/{article_id}` enforces case/task scope
and never fetches arbitrary article IDs. The existing source route accepts validated
knowledge references and safely serves pasted-document text when appropriate.
Word and audit JSON outputs use the existing versioned task publication protocol.
The frontend can explicitly add an article using the existing case-research API;
recommendation generation performs no article-association writes. Article opening
uses version-1 `apex:workflow-open-article` with articleId, accepted only from a
same-origin registered CASE_WORKFLOWS iframe.

## AI context and scoped memory

`backend/ai_context.py` owns migration 21, request-scoped context construction,
scoped recall and persisted extraction jobs. Only new messages explicitly marked
eligible after the migration epoch participate; legacy messages remain viewable.
`history_key` and `current_message_id` identify the saved current request across
all ask scopes and both file endpoints. The server validates conversation/message
ownership and explicit case IDs. Mixed-case conversations do not borrow case memory.

History saves upsert stable message IDs, synchronize removals, and optionally
compare the conversation revision. New UI clients always send the revision.
`context_usage` records the selected memories, summary version and source messages.
`GET/PUT /api/ai-context` exposes summary/recall/exclusions with optimistic revision
checks; `POST /api/ai-context/rebuild` explicitly retries/rebuilds eligible content.
User-memory status and version endpoints support confirmation and audit history.

A single bounded worker runs after a successful answer is persisted, using that
answer's selected model. Jobs persist across restart, deduplicate by user message,
and recheck conversation, summary and memory revisions before committing. Only
verbatim user spans can become automatic memories; assistant legal conclusions
are not extracted as facts. Conflicts suspend both alternatives until confirmation.
Deleted/edited memory content is suppressed against automatic re-creation.
Per-turn no-memory messages remain in current-chat context but cannot be mined
or recalled across chats. Deleting a conversation removes derived context while
retaining separately saved memories with a missing-source indicator.

Input accounting uses a conservative UTF-8 byte upper bound and reserves response
space. `STELLA_AI_INPUT_BUDGETS` optionally maps catalog model IDs to application
budgets; the default is 24000, not a provider context-window claim. Full prompts
are checked before provider calls, including actual fallback output allowances.
Insufficient space returns an explicit 413; original source data is preserved.
