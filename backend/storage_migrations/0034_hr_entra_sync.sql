CREATE TABLE IF NOT EXISTS hr_entra_sync_issues (
    issue_key        TEXT PRIMARY KEY,
    project_key      TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'pending',
    first_seen_at    TEXT NOT NULL,
    last_attempt_at  TEXT NOT NULL DEFAULT '',
    attempts         INTEGER NOT NULL DEFAULT 0,
    completed_at     TEXT NOT NULL DEFAULT '',
    matched_upn      TEXT NOT NULL DEFAULT '',
    matched_via      TEXT NOT NULL DEFAULT '',
    fields_written   TEXT NOT NULL DEFAULT '[]',
    fields_skipped   TEXT NOT NULL DEFAULT '{}',
    error            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_hr_entra_sync_issues_status ON hr_entra_sync_issues (status);
