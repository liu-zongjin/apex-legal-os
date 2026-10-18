# Stella public Preview 3 verification — 2026-10-18

Public-only snapshot overlays provide editable/hidden username, default-hidden greeting aligned with the brand, separate document firm name/logo, and customization-only letter approval, quick approval, meeting reservation, and scanner inbox entries. Legal document titles remain 授权委托书 / 法定代表人证明书 / 业务审批表. The original firm number prefixes are neutralized.

## Isolation

The primary private checkout remains on its existing branch and commit. All 191 tracked backend/frontend/native source fingerprints match the pre-change snapshot. The existing private server on port 8000 remains running. No private app replacement, restart, database operation, or runtime setting change was performed. New work lives in this separate public-distribution worktree and branch; private runtime modules never import the public overlays.

## Validation

- Extended guard: 953 tests passed, schema and API contracts passed. Final focused builder suite: 8 tests; public-profile suite: 3 tests.
- Actual frozen executable: isolated runtime, demo-data/credential/OCR self-test passed; 16 feature-page checks across Chromium and WebKit passed.
- Username editing, visibility, greeting default, persistence and no brand displacement checked in both engines. Dark settings and mobile layout checked.
- Firm logo upload, reload persistence, removal and firm-name save checked in both engines.
- Four actual Word exports checked for standard titles, uploaded logo presence and bounded dimensions. Custom integration endpoints return 501 before integration execution.
- Package audit, ad-hoc codesign and ZIP validation passed. SHA-256: `11aba253ec8a339678231b54449e69d41f69ac5a24a39f7989fbe6ec611e793d`.
- Static website passed desktop/mobile checks in Chromium and WebKit, including loaded local assets, download targets and FAQ. Live GitHub Pages URL returned 200 and rendered successfully.

## Limits and recovery

Apple notarization is not included. External AI/mail/court accounts were not exercised with real credentials. Office conversion availability depends on the recipient's installed converter. Public integration entries intentionally require customization. Recovery point before changes: 6688e50; public app build source: bb5afd8. Private source stays untouched; revert the public distribution branch or download previous release for rollback.
