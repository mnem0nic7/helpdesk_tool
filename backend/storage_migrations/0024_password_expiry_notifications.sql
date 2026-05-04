CREATE TABLE IF NOT EXISTS password_expiry_notifications (
    id                  TEXT PRIMARY KEY,
    sam_account_name    TEXT NOT NULL,
    email               TEXT NOT NULL,
    expiry_date         TEXT NOT NULL,
    days_until_expiry   INTEGER NOT NULL,
    notified_at         TEXT NOT NULL,
    test_mode           SMALLINT NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_pen_sam_date
    ON password_expiry_notifications (sam_account_name, notified_at);

CREATE TABLE IF NOT EXISTS password_expiry_notify_runs (
    run_date        TEXT PRIMARY KEY,
    ran_at          TEXT NOT NULL,
    users_notified  INTEGER NOT NULL DEFAULT 0,
    test_mode       SMALLINT NOT NULL DEFAULT 1
);
