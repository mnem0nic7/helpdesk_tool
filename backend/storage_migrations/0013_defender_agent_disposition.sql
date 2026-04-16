ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS disposition TEXT;

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS disposition_note TEXT NOT NULL DEFAULT '';

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS disposition_by TEXT NOT NULL DEFAULT '';

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS disposition_at TEXT;

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS investigation_notes_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE defender_agent_decisions
    ADD COLUMN IF NOT EXISTS watchlisted_entities_json TEXT NOT NULL DEFAULT '[]';
