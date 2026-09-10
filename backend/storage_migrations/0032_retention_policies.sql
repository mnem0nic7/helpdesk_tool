CREATE TABLE IF NOT EXISTS retention_policies (
    id             TEXT PRIMARY KEY,
    team_id        TEXT NOT NULL,
    team_name      TEXT NOT NULL DEFAULT '',
    channel_id     TEXT NOT NULL,
    channel_name   TEXT NOT NULL DEFAULT '',
    retention_days INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending_preview',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_retention_policies_channel
    ON retention_policies (team_id, channel_id);

CREATE TABLE IF NOT EXISTS retention_runs (
    id                  TEXT PRIMARY KEY,
    policy_id           TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    outcome             TEXT NOT NULL DEFAULT 'running',
    messages_deleted    INTEGER NOT NULL DEFAULT 0,
    attachments_deleted INTEGER NOT NULL DEFAULT 0,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_retention_runs_policy
    ON retention_runs (policy_id);

CREATE TABLE IF NOT EXISTS retention_deletions (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    item_type           TEXT NOT NULL,
    item_id             TEXT NOT NULL,
    sender_or_author    TEXT NOT NULL DEFAULT '',
    original_created_at TEXT NOT NULL DEFAULT '',
    deleted_at          TEXT NOT NULL,
    status              TEXT NOT NULL,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_retention_deletions_run
    ON retention_deletions (run_id);
