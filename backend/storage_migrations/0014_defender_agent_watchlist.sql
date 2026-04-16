CREATE TABLE IF NOT EXISTS defender_agent_watchlist (
    id           TEXT PRIMARY KEY,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    entity_name  TEXT NOT NULL DEFAULT '',
    reason       TEXT NOT NULL DEFAULT '',
    boost_tier   SMALLINT NOT NULL DEFAULT 0,
    created_by   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    active       SMALLINT NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_defender_watchlist_entity
    ON defender_agent_watchlist (entity_id, active);
