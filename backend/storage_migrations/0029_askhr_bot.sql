CREATE TABLE IF NOT EXISTS askhr_bot_settings (
    id                              INTEGER PRIMARY KEY DEFAULT 1,
    enabled                         SMALLINT NOT NULL DEFAULT 0,
    poll_interval_seconds           INTEGER NOT NULL DEFAULT 120,
    lookback_minutes                INTEGER NOT NULL DEFAULT 15,
    askhr_checkpoint_at             TEXT NOT NULL DEFAULT '',
    benefits_checkpoint_at          TEXT NOT NULL DEFAULT '',
    trusted_domains                 TEXT NOT NULL DEFAULT '[]',
    trusted_domains_refreshed_at    TEXT NOT NULL DEFAULT '',
    domain_refresh_interval_seconds INTEGER NOT NULL DEFAULT 3600,
    reporter_mode                   TEXT NOT NULL DEFAULT 'unset',
    updated_at                      TEXT NOT NULL DEFAULT '',
    updated_by                      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS askhr_bot_runs (
    id               TEXT PRIMARY KEY,
    mailbox          TEXT NOT NULL,
    run_started_at   TEXT NOT NULL,
    messages_scanned INTEGER NOT NULL DEFAULT 0,
    created_count    INTEGER NOT NULL DEFAULT 0,
    skipped_count    INTEGER NOT NULL DEFAULT 0,
    failed_count     INTEGER NOT NULL DEFAULT 0
);

-- The same email (same Message-ID) can be addressed to both AskHR@ and
-- Benefits@, and each mailbox must get its own HRD ticket, so the identity of
-- a row is (mailbox, internet_message_id) -- not internet_message_id alone.
CREATE TABLE IF NOT EXISTS askhr_bot_messages (
    internet_message_id TEXT NOT NULL,
    mailbox             TEXT NOT NULL,
    graph_message_id    TEXT NOT NULL,
    subject             TEXT NOT NULL DEFAULT '',
    sender_email        TEXT NOT NULL DEFAULT '',
    received_at         TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL,
    jira_issue_key      TEXT,
    error               TEXT,
    processed_at        TEXT NOT NULL,
    PRIMARY KEY (mailbox, internet_message_id)
);

CREATE INDEX IF NOT EXISTS idx_askhr_bot_messages_mailbox_received
    ON askhr_bot_messages (mailbox, received_at);
