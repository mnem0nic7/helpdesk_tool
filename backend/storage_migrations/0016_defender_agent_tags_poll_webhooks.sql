ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS tags_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE defender_agent_config
    ADD COLUMN IF NOT EXISTS poll_interval_seconds INTEGER NOT NULL DEFAULT 0;

ALTER TABLE defender_agent_config
    ADD COLUMN IF NOT EXISTS teams_tier1_webhook TEXT NOT NULL DEFAULT '';

ALTER TABLE defender_agent_config
    ADD COLUMN IF NOT EXISTS teams_tier2_webhook TEXT NOT NULL DEFAULT '';

ALTER TABLE defender_agent_config
    ADD COLUMN IF NOT EXISTS teams_tier3_webhook TEXT NOT NULL DEFAULT '';
