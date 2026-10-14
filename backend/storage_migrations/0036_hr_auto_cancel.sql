CREATE TABLE IF NOT EXISTS hr_auto_cancel_actions (
    issue_key      TEXT PRIMARY KEY,
    project_key    TEXT NOT NULL DEFAULT '',
    sender         TEXT NOT NULL DEFAULT '',
    from_status    TEXT NOT NULL DEFAULT '',
    to_status      TEXT NOT NULL DEFAULT '',
    result         TEXT NOT NULL DEFAULT 'pending',
    attempts       INTEGER NOT NULL DEFAULT 0,
    first_seen_at  TEXT NOT NULL,
    acted_at       TEXT NOT NULL DEFAULT '',
    error          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_hr_auto_cancel_actions_result ON hr_auto_cancel_actions (result);
