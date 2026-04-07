CREATE TABLE IF NOT EXISTS deactivation_schedule (
    job_id          TEXT PRIMARY KEY,
    ticket_key      TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    entra_user_id   TEXT NOT NULL,
    ad_sam          TEXT NOT NULL DEFAULT '',
    run_at          TEXT NOT NULL,
    timezone_label  TEXT NOT NULL DEFAULT 'UTC',
    status          TEXT NOT NULL DEFAULT 'pending',
    result_json     TEXT,
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_deact_status ON deactivation_schedule (status, run_at);
CREATE INDEX IF NOT EXISTS idx_deact_ticket ON deactivation_schedule (ticket_key);
