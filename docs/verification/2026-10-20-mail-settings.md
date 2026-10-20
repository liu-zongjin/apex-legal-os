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
