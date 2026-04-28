CREATE INDEX IF NOT EXISTS idx_defender_decisions_decision
    ON defender_agent_decisions (decision, executed_at DESC);
