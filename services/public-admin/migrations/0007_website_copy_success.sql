-- Separate table preserves the old interaction CHECK and historical click meaning.
CREATE TABLE website_copy_success (
 id TEXT PRIMARY KEY, visitor TEXT NOT NULL, session TEXT NOT NULL,
 at INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind='copy_success'),
 page TEXT NOT NULL CHECK(page='download-guide'), detail TEXT NOT NULL,
 country TEXT NOT NULL, region TEXT NOT NULL, device TEXT NOT NULL,
 os TEXT NOT NULL, browser TEXT NOT NULL
);
CREATE INDEX website_copy_success_time ON website_copy_success(at);
