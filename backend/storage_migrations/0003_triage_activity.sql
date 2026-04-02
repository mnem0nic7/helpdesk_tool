CREATE TABLE IF NOT EXISTS triage_auto_triage_activity (
    key TEXT PRIMARY KEY,
    outcome TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'auto',
    processed_at TEXT NOT NULL,
    model TEXT,
    fields_changed TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    legacy_backfill INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_triage_activity_processed_at
    ON triage_auto_triage_activity(processed_at DESC);

CREATE INDEX IF NOT EXISTS idx_triage_activity_outcome
    ON triage_auto_triage_activity(outcome, processed_at DESC);
