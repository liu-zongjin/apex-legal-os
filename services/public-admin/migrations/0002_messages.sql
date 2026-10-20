-- Public announcements contain only administrator-authored public text.
CREATE TABLE system_messages (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  published_at INTEGER NOT NULL,
  withdrawn_at INTEGER
);
CREATE INDEX system_messages_feed ON system_messages(withdrawn_at, published_at DESC, id);
