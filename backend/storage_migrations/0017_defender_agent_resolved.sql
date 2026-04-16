ALTER TABLE defender_agent_decisions ADD COLUMN IF NOT EXISTS resolved     SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE defender_agent_decisions ADD COLUMN IF NOT EXISTS resolved_at  TEXT;
ALTER TABLE defender_agent_decisions ADD COLUMN IF NOT EXISTS resolved_by  TEXT NOT NULL DEFAULT '';
