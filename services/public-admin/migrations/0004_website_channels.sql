-- Existing events have no reliable download channel; never infer it retroactively.
ALTER TABLE website_events ADD COLUMN channel TEXT NOT NULL DEFAULT 'unknown'
  CHECK(channel IN ('unknown','quark','github'));
