CREATE TABLE IF NOT EXISTS password_expiry_notifier_settings (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    enabled     SMALLINT NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT ''
);
