ALTER TABLE defender_agent_decisions
  ADD COLUMN IF NOT EXISTS alert_raw_json TEXT NOT NULL DEFAULT '';
