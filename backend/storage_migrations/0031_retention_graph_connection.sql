CREATE TABLE IF NOT EXISTS retention_graph_connection (
    id                      INTEGER PRIMARY KEY DEFAULT 1,
    service_account_upn     TEXT NOT NULL DEFAULT '',
    encrypted_refresh_token TEXT NOT NULL DEFAULT '',
    access_token_cache      TEXT NOT NULL DEFAULT '',
    access_token_expires_at TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'disconnected',
    last_refreshed_at       TEXT,
    last_error              TEXT,
    connected_by            TEXT NOT NULL DEFAULT '',
    connected_at            TEXT NOT NULL DEFAULT ''
);
