# Workspace mailbox configuration

Date: 2026-10-20 (Asia/Shanghai).
Branch: `codex/mail-settings-20261020`; recovery checkpoint `68682ba`.

- Three workspace entries open the allowlisted mail view of the existing MCP
  manager: WeCom/Tencent enterprise, NetEase enterprise, and QQ Mail.
- One credential drawer, persistence path, masked response and connection test
  remain shared with ordinary MCP management. Generic MCP navigation resets the
  filtered view. No credentials are carried in query parameters.
- Shared three-step instructions include official webmail entrances, how to obtain
  client authorization, saving/testing, administrator permission troubleshooting,
  and optional large-attachment sessions. Webmail UI labels can vary by provider.
- Review found existing API payloads expose protocol_label without protocol;
  mail input handling now also recognizes the three registered provider IDs.
  Browser fixtures intentionally omit protocol to match this existing contract.
- Keyboard modal focus stays inside the drawer and returns to its trigger; hiding
  the overview explicitly overrides its grid display. Generated bootstrap and
  offline shell 267 are synchronized; no user caches or cases are cleared.

Verification:

- Extended checks passed: 988 tests, 222 Python / 77 JavaScript syntax checks,
  unchanged 841-route API contract. All database/config/runtime paths were temporary.
  An initial cache-version assertion caught the changed bootstrap URL; the worker
  cache and shell versions were corrected before the passing complete run.
- Isolated browser suite passed: all three actual settings entry handlers, provider
  isolation, fake credential saves, blank-key preservation, masks, mocked connection
  tests, generic catalog return, keyboard controls, invalid-query fallback, and
  1440/1024/390 light/dark layouts. Screenshots contain anonymous fixtures only.
- Native Stella was refreshed: all three entries visibly appear under 工作空间 →
  服务与资料, and the enterprise-mail entry opened its dedicated page and guide.
  No live mailbox credentials were changed and no real mail was sent or deleted.
- Final mailbox compatibility changes passed the same isolated browser suite and
  fast guard checks. No installer, delta, website package or appcast was published.

## Follow-up: one entry and secondary mailbox menu

Per the user's follow-up, the three workspace entries are now one 邮箱配置 entry.
The page provides three accessible secondary tabs and displays the shared form
inline so a drawer cannot obstruct switching. Existing per-account query links and
the generic MCP manager remain compatible. Unsaved addresses/authorization entries
and explicit clear flags remain separate in page memory only; switching never
writes a credential or borrows another account's values. A successful save refreshes
its mask and discards that account's submitted draft. Switching is blocked while a
save is in progress. Arrow/Home/End keyboard navigation updates the selected panel.

The updated isolated browser suite passed including independent drafts and no-save
switching, one workspace entry, all three tabs, account save/mask/testing and ordinary
MCP modal behavior. Light/dark screenshots were inspected at 1024 and 390 pixels;
the shared theme adapter receives the fixture's storage event before capture.
Extended checks passed all 988 tests with temporary runtime/config/data paths and
the unchanged API contract; final responsive styling also passed the browser suite
and fast checks. Shell 268 retains the changed bootstrap URL. No public release.
The native Mac became locked, so this follow-up's final native-window refresh was
not performed; browser verification uses the actual HTML and settings handlers.
