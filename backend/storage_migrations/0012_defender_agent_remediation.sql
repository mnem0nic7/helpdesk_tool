ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS remediation_confirmed SMALLINT NOT NULL DEFAULT 0;

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS remediation_failed SMALLINT NOT NULL DEFAULT 0;

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS confirmed_at TEXT;

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS confidence_score INTEGER NOT NULL DEFAULT 0;

ALTER TABLE defender_agent_config
    ADD COLUMN IF NOT EXISTS min_confidence INTEGER NOT NULL DEFAULT 0;
