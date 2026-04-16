CREATE TABLE IF NOT EXISTS defender_agent_rule_overrides (
    rule_id          TEXT PRIMARY KEY,
    disabled         SMALLINT NOT NULL DEFAULT 0,
    confidence_score INTEGER,
    updated_at       TEXT NOT NULL DEFAULT '',
    updated_by       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS defender_agent_custom_rules (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL DEFAULT '',
    match_field      TEXT NOT NULL DEFAULT 'title',
    match_value      TEXT NOT NULL DEFAULT '',
    match_mode       TEXT NOT NULL DEFAULT 'contains',
    tier             INTEGER NOT NULL DEFAULT 3,
    action_type      TEXT NOT NULL DEFAULT 'start_investigation',
    confidence_score INTEGER NOT NULL DEFAULT 50,
    enabled          SMALLINT NOT NULL DEFAULT 1,
    created_by       TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT ''
);
