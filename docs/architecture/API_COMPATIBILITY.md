# API Compatibility

- Adding an optional response field is compatible.
- Removing or renaming a route, parameter, or response field is breaking.
- Changing a field type, meaning, default, ordering guarantee, or error behavior is
  breaking even when the field name stays the same.
- Breaking changes require an impact report, a compatibility adapter or migration,
  updated consumers, contract snapshot, tests, changelog entry, and explicit
  verification of every registered consumer.
- API snapshots describe surface compatibility; behavior tests remain required.

