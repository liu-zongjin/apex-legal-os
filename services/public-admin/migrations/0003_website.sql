-- Independent website events; no IP, raw User-Agent, full URL or query strings.
CREATE TABLE website_events (
  id TEXT PRIMARY KEY, visitor TEXT NOT NULL, session TEXT NOT NULL,
  at INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('pageview','section','download')),
  section TEXT NOT NULL, target TEXT NOT NULL, referrer TEXT NOT NULL,
  country TEXT NOT NULL, region TEXT NOT NULL, device TEXT NOT NULL,
  os TEXT NOT NULL, browser TEXT NOT NULL
);
CREATE INDEX website_events_time ON website_events(at);
CREATE TABLE website_meta (id INTEGER PRIMARY KEY CHECK(id=1), started_at INTEGER NOT NULL);
