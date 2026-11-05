-- Historical reports cannot reveal the installation method.
ALTER TABLE installations ADD COLUMN channel TEXT NOT NULL DEFAULT 'unknown';
CREATE TABLE application_samples (
 installation_id TEXT NOT NULL, at INTEGER NOT NULL,
 PRIMARY KEY(installation_id,at)
);
CREATE INDEX application_samples_at ON application_samples(at);
