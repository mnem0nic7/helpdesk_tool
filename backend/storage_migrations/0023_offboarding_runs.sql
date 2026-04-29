CREATE TABLE IF NOT EXISTS offboarding_runs (
    run_id              TEXT PRIMARY KEY,
    entra_user_id       TEXT NOT NULL DEFAULT '',
    ad_sam              TEXT NOT NULL DEFAULT '',
    display_name        TEXT NOT NULL DEFAULT '',
    actor_email         TEXT NOT NULL DEFAULT '',
    lanes_requested     TEXT NOT NULL,        -- JSON array of lane names
    status              TEXT NOT NULL DEFAULT 'queued',
    has_errors          SMALLINT NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    started_at          TEXT,
    finished_at         TEXT
);

CREATE TABLE IF NOT EXISTS offboarding_run_steps (
    step_id             TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    lane                TEXT NOT NULL,
    sequence            INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'queued',
    message             TEXT NOT NULL DEFAULT '',
    detail_json         TEXT,
    started_at          TEXT,
    finished_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_offboarding_runs_created ON offboarding_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_offboarding_run_steps_run ON offboarding_run_steps (run_id, sequence);
