-- AI-08: security lane AI summary cache
CREATE TABLE IF NOT EXISTS security_lane_ai_summaries (
    lane_key     TEXT PRIMARY KEY,
    narrative    TEXT NOT NULL DEFAULT '',
    teaser       TEXT NOT NULL DEFAULT '',
    bullets_json TEXT NOT NULL DEFAULT '[]',
    generated_at TEXT NOT NULL DEFAULT '',
    model_used   TEXT NOT NULL DEFAULT ''
);
