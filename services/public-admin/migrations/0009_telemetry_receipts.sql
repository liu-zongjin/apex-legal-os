-- Historical last_seen remains the fallback; do not invent receipt timestamps.
CREATE TABLE telemetry_receipts(installation_id TEXT PRIMARY KEY, received_at INTEGER NOT NULL);
CREATE INDEX telemetry_receipts_time ON telemetry_receipts(received_at);
CREATE TABLE telemetry_health(day TEXT NOT NULL,outcome TEXT NOT NULL,count INTEGER NOT NULL,last_at INTEGER NOT NULL,PRIMARY KEY(day,outcome));
