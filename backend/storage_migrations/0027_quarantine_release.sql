CREATE TABLE IF NOT EXISTS quarantine_release_settings (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    enabled         SMALLINT NOT NULL DEFAULT 0,
    allowed_domains TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT '',
    updated_by      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quarantine_release_runs (
    run_hour        TEXT PRIMARY KEY,
    ran_at          TEXT NOT NULL,
    domains_checked TEXT NOT NULL,
    checked_count   INTEGER NOT NULL DEFAULT 0,
    released_count  INTEGER NOT NULL DEFAULT 0,
    failed_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quarantine_releases (
    id                TEXT PRIMARY KEY,
    run_hour          TEXT NOT NULL,
    message_identity  TEXT NOT NULL,
    sender_address    TEXT NOT NULL,
    recipient_address TEXT NOT NULL,
    subject           TEXT NOT NULL DEFAULT '',
    received_at       TEXT NOT NULL DEFAULT '',
    quarantine_reason TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL,
    error             TEXT,
    released_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qr_run_hour
    ON quarantine_releases (run_hour);
