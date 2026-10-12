CREATE TABLE IF NOT EXISTS e5_license_report_runs (
    run_date    TEXT PRIMARY KEY,
    sent_at     TEXT NOT NULL,
    recipients  TEXT NOT NULL DEFAULT '',
    row_count   INTEGER NOT NULL DEFAULT 0
);
