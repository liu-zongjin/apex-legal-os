-- Site interactions that are not pageviews, section views or download clicks.
-- Only anonymous visitor/session hashes, coarse request-derived categories and
-- public control identifiers; no URL, query, page text, file name or account.
CREATE TABLE website_interactions (
  id TEXT PRIMARY KEY, visitor TEXT NOT NULL, session TEXT NOT NULL,
  at INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('copy','tab','video','chapter','assistant')),
  page TEXT NOT NULL CHECK(page IN ('download-guide','watch')),
  detail TEXT NOT NULL,
  country TEXT NOT NULL, region TEXT NOT NULL, device TEXT NOT NULL,
  os TEXT NOT NULL, browser TEXT NOT NULL
);
CREATE INDEX website_interactions_time ON website_interactions(at);
CREATE INDEX website_interactions_kind_time ON website_interactions(kind, at);
