# Contributing to Stella / APEX

Stella / APEX is maintained by LIU Zongjin. Contributions should improve reusable
legal workflow tools while protecting private user data.

Before opening an issue, remove client names, case records, court account details,
tokens, private paths and identifying screenshots. Prefer a minimal reproduction
with fictional data. Report security concerns privately as described in SECURITY.

For a proposed change, explain the problem and expected behavior, search existing
issues and read AGENTS.md and the architecture documents. Keep the change focused
and consider every consumer of a shared component. Run the repository's preflight
and the checks relevant to the change. Use temporary databases and synthetic
fixtures. Never test against a real user's database or browser session.

Pull requests should include the reason for the change, relevant validation and
any workflows that were not exercised. Changes remain subject to maintainer
review. Source contributions do not authorize publishing installers or updates.

Original project code is licensed under AGPL-3.0-only, with third-party rights retained as described in NOTICE.md and THIRD_PARTY_NOTICES.md.
By submitting a contribution, you must have the right to contribute it under the
license applicable to the affected files. Preserve all third-party notices.
