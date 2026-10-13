# Download audit, 2026-10-13

| Source | Before | Updated behavior | Isolated validation |
| --- | --- | --- | --- |
| 网易企业邮箱 | Synchronous attachment collection, no bar, shared invoice directory | Explicit purpose/bound-case confirmation, managed task, unknown IMAP phase then attachment save counters | Fake MIME mailbox job, case/invoice separation and binding failures |
| QQ邮箱 | Same shared mailbox UI and backend | Same adapter, source/account retained | Fake mailbox and sent-folder tests |
| 一张网 | Dossier progress existed; individual/all delivery attachments had no bar | Keep dossier executor; stream attachment bytes through managed jobs; ZIP native copy tracked | Streaming HTTP fixtures, bound-case destination tests |
| 司法短信 | Existing live bar | Preserve bar; mirror live counters and original file/case records into center | Multi-file known/unknown-size and partial-failure fixtures |
| 文书生成 | Five generators triggered browser files and local history | Preparation + actual response-byte bar + staged artifacts; direct case-save routes monitored/indexed | Streaming export UI; existing generator/case automation tests |
| AI增强 | Word/Markdown export, little history/context | Stream both blob and array-buffer paths; preserve stored question/research case context | Anonymous export stream and UI tests |
| 发票中心 | Packaging text only; automation ZIP link bypassed progress | Explicit monitored scan/ZIP and automation ZIP transfer; invoice remains independent | Response stream, metadata separation and UI fixtures |

## Center and native checks

- Temp databases/folders only: metadata persistence, interrupted recovery, exact destinations, confirmation, no overwrite, invoice guard, path/PATCH/symlink rejection, idempotent legacy import, pagination/filters, metadata-only cleaning.
- Native candidate file must have identical size and streamed SHA256 to its managed source before arbitrary user-selected save location is recorded.
- Anonymous browser screenshots cover 1440x900 and 1024x768 in light/dark, mobile width, case confirmation and actual multi-chunk response bytes; no real names/messages/tokens are used.
- Native shell is typechecked and built against the local macOS SDK. Automated browser fixtures exercise its event adapter; real WKDownload observation/save-panel flow requires application relaunch and user review.
- Live mailbox/court authentication, real recipient verification, and actual production case writes are not exercised by tests.
