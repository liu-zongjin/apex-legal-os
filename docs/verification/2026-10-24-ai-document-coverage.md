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
