# AI Enhance document coverage — 2026-10-24

Scope: canonical local source only. Both attachment and bound-case file questions
share the selector. No public package, update feed, migration or dependency change.
Recovery point: `615cd64`, also named `recovery/ai-documents-before-fix`.
Review branch: `fix/ai-document-coverage`; user workflow confirmation precedes merge.

## Reproduction

Read-only inspection of the retained two-file upload session confirmed that both
parsed texts contain the previously omitted reasoning and final outcome.
Replaying the old selector from the recovery revision with the same question and
`deepseek-flash` budget reproduced exactly eight passages and partial coverage:
file A supplied 462 characters (no reasoning/outcome), file B 3,367 (no outcome).
The new selector supplied all five indexed passages: A 8,038 characters, B 5,296,
both including reasoning and outcome. Counts include existing index overlap and
are extraction coverage, not proof of faithful source-format parsing.
No private source filenames or document contents are copied into this report.

## Implementation

- Complete extracted texts when affordable; remove the 18-short-span ceiling.
- Longer inputs: local BM25-style query relevance, generic headings, adaptive
  marginal relevance, duplicate/section/position diversity, and fair file rounds.
- Preserve exact original spans and index-relative character locators. Budget
  includes output reserve, skills, coverage metadata and framing. No extra AI calls.
- Prompt and existing trace expose supplied/extracted counts. Distinguish passage
  IDs from files and unprovided evidence from absence in the original document.
- These are retrieval heuristics, not a guarantee of semantic recall for arbitrary
  long documents. Partial coverage remains explicit. No format-specific court
  section whitelist is used.

## Verification

- `python3 scripts/apex_guard.py extended`: passed; 1,113 tests, 26 skipped;
  Python/JavaScript syntax, secret scan and unchanged API contract passed.
- `tests.test_case_files`: 32 passed, including complete multi-file texts beyond
  18 spans, unstructured document endings, technical thresholds/negation,
  CSV rows, skill/model budgets and file fairness.
- Both HTTP flows tested with anonymous temporary files/database and a provider
  stub: upload/prepare/ask and bound-case prepare/ask. Both deliver full originals
  and coverage to the provider boundary. No live database writes in these tests.
- `tests/ai_context_ui.js`, `tests/ai_parallel_chats_ui.js`,
  `tests/user_memory_ui.js`: passed with bundled Playwright and installed Chrome.
- Local server status: running, restart_required false after source reload.
- Existing Stella answer visually inspected through accessibility; unchanged old
  response remains visible. No real-provider regeneration or arbitrary-format OCR
  accuracy evaluation was performed. Existing historical answers are not rewritten.

## Second review and debugging

Review baseline and recovery: `175bb5e`, also named
`recovery/ai-documents-before-review`. Changes stay on the same review branch.

Findings fixed:

1. **P1 — blocking and repeated work.** Selection was called directly in async
   request handlers and recalculated similarity against all prior selections on
   every round. Synchronous upload parsers also ran in the event loop. Both now
   run in workers with copied request context; incremental similarity/position
   updates remove repeated prior-selection scans. Cancellation signals the
   selection worker cooperatively. Synchronous parsing already in progress can
   still finish in its worker after request cancellation.
2. **P1 — detached context.** The 1,000-character selection boundaries could
   separate a matching sentence from an immediately following condition; inherited
   headings influenced ranking without entering the supplied evidence. Excerpts
   now include bounded neighboring original text and sentence/line boundaries;
   inherited headings enter locators, and exact offsets remain verifiable.
3. **P1 — supplementary evidence overflow.** A fixed character slice of the
   authoritative result could exceed the remaining byte budget after complete
   local documents were included. The old append strategy produced 75,219 bytes
   including output reserve in a 64,000-byte budget in an anonymous reproduction.
   Unified prompt construction now admits supplementary blocks only when the full
   framed request fits. Excluded blocks get explicit warnings and no source cards.
   Public-web results undergo the same final check. Local files retain priority.
4. **P2 — source identity and fallback cards.** Attachment fallback previously
   selected the first N passages instead of the first passage of each distinct
   file. Missing or entirely invalid citation markers now fall back per file in
   both routes. Explicit source identifiers distinguish identical display names.

Verification on the final implementation:

- Extended guard passed: **1,120 tests, 26 skipped**; syntax, secret scanning and
  unchanged API contract passed. Feature suite: **39 passed**.
- Added regression cases cover conditions crossing the previous span boundary,
  exact original-text offsets, inherited headings, equal filenames, missing/invalid
  citations, rendered prompt sizes with long names/skills/small request budgets,
  worker request-context propagation, cooperative cancellation, and sync/async
  parser compatibility. Both actual HTTP routes retain their provider-stub tests;
  optional external sources are checked in both admitted and rejected cases.
- Anonymous 132,779-character, 1,500-heading local responsiveness reproduction:
  before 7.939 seconds / 69 passages; after 0.084 seconds / 22 larger contextual
  passages in one warm-process comparison. These are local measurements; the new
  excerpt framing also changes passage sizes, so this is not a controlled ranking
  algorithm benchmark or a semantic-recall measurement.
- Original incident retained-session recheck: both files still supply all extracted
  text, with 17,168 bytes of remaining budget after current framing/reserves.
- Local server reports running and restart_required false. No live model answer
  regeneration, public package, database migration, or public release performed.
- The prior UI harness checks remain applicable: no frontend behavior changed in
  this review. Retrieval remains heuristic for over-budget documents; bounded
  neighboring text cannot guarantee every distant qualification is retrieved.
