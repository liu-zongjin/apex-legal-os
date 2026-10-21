# Case record editor stability review — 2026-10-21

## Findings and fixes

- Pagination cached the editor's viewport top before inserting/removing page
  spacers. Browser viewport anchoring during layout could invalidate that origin,
  leading to incorrect page coordinates, repeated splitting and excessive work.
  Measurements now use the current origin. Repeated split positions, a 180 ms
  budget and a 500-page presentation limit provide a lossless continuous-mode
  fallback. Ordinary documents retain A4 presentation when pagination completes.
- A delayed opening-position callback could reposition a subsequently opened
  editor. It now verifies the opening context is still active.
- Markdown-source transitions now retain the previous reading progress.
- Spreadsheet exports previously included stored rich-text HTML tags. Exported
  text now retains paragraphs, inline words, list labels and source URLs.

## Verification

- Old-source comparison: `70ed5db` fails the WebKit regression that changes the
  viewport during a page-spacer insertion in an anonymous multi-page record.
  Text falls outside page bounds. The corrected source passes the same case.
- Chromium and WebKit pagination suites pass: anonymous record structure,
  mixed inline formats, long paragraphs, nested lists/blocks, tables, oversized
  rows, images, repeated layout, selection, composition, margins and dark mode.
- Deterministic budget exhaustion removes temporary spacers and preserves HTML.
- Record browser checks pass for empty drafts, direct editing, full-formatting
  apply/cancel, stale drafts, normal view/edit/save scroll retention, formatting
  scroll retention, attachment rollback/retry, keyboard and responsive geometry.
- Extended guard: 1,035 tests, 13 skipped; no failures. Public-admin Node tests:
  18 passed. Spreadsheet export tests: 4 passed.
- Native AppKit/WKWebView process was not force-restarted or modified during
  testing. Browser verification uses Chromium and WebKit rather than claiming
  direct observation of every native-app freeze.

Only anonymous fixtures are committed; local record content is not included.
