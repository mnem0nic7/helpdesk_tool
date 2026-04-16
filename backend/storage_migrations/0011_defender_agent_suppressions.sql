CREATE TABLE IF NOT EXISTS defender_agent_suppressions (
    id                TEXT PRIMARY KEY,
    suppression_type  TEXT NOT NULL,
    value             TEXT NOT NULL,
    reason            TEXT NOT NULL DEFAULT '',
    created_by        TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    expires_at        TEXT,
    active            SMALLINT NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_defender_suppressions_active
    ON defender_agent_suppressions (active, expires_at);

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS action_types_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS mitre_techniques_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE defender_agent_config
    ADD COLUMN IF NOT EXISTS entity_cooldown_hours INTEGER NOT NULL DEFAULT 24;

ALTER TABLE defender_agent_config
    ADD COLUMN IF NOT EXISTS alert_dedup_window_minutes INTEGER NOT NULL DEFAULT 30;
