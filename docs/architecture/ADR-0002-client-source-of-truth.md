# ADR-0002: Client archive is the client source of truth

- Status: accepted
- Date: 2026-09-06

The client archive managed by case management is the authoritative source for
client choices and profiles. Document generators use the shared client adapter and
picker. They may retain feature-specific selected values but may not create a
second client archive.

Legacy document-generator option endpoints remain compatible during migration.
They must not be removed until all registered consumers have migrated and the API
contract documents the removal.

