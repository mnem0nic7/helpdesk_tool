ALTER TABLE defender_agent_decisions
  ADD COLUMN IF NOT EXISTS alert_written_back SMALLINT NOT NULL DEFAULT 0;
