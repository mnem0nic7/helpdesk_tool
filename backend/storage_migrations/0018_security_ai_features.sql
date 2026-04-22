-- AI narrative for Defender Agent decisions (AI-03)
ALTER TABLE defender_agent_decisions ADD COLUMN IF NOT EXISTS ai_narrative TEXT;
ALTER TABLE defender_agent_decisions ADD COLUMN IF NOT EXISTS ai_narrative_generated_at TEXT;

-- KB category for security runbooks (AI-06)
ALTER TABLE kb_articles ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_kb_articles_category ON kb_articles(category);

-- Security runtime config for site-wide model picker (AI-05)
CREATE TABLE IF NOT EXISTS security_runtime_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
