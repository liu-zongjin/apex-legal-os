-- No user content, email, IP, or raw installation identifier is stored here.
CREATE TABLE installations (
  id TEXT PRIMARY KEY, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
  version TEXT NOT NULL, os TEXT NOT NULL
);
CREATE INDEX installations_recent ON installations(last_seen);
CREATE TABLE daily_activity (
  day TEXT NOT NULL, installation_id TEXT NOT NULL,
  PRIMARY KEY(day, installation_id)
);
CREATE TABLE download_snapshots (
  id INTEGER PRIMARY KEY CHECK(id=1), total INTEGER NOT NULL,
  checked_at INTEGER NOT NULL, assets_json TEXT NOT NULL
);
