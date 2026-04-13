CREATE TABLE IF NOT EXISTS defender_agent_config (
    id                    INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled               BOOLEAN NOT NULL DEFAULT FALSE,
    min_severity          TEXT    NOT NULL DEFAULT 'high',
    tier2_delay_minutes   INTEGER NOT NULL DEFAULT 15,
    dry_run               BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at            TEXT    NOT NULL DEFAULT '',
    updated_by            TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS defender_agent_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    alerts_fetched  INTEGER NOT NULL DEFAULT 0,
    alerts_new      INTEGER NOT NULL DEFAULT 0,
    decisions_made  INTEGER NOT NULL DEFAULT 0,
    actions_queued  INTEGER NOT NULL DEFAULT 0,
    error           TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_defender_runs_started
    ON defender_agent_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS defender_agent_decisions (
    decision_id         TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    alert_id            TEXT NOT NULL,
    alert_title         TEXT NOT NULL DEFAULT '',
    alert_severity      TEXT NOT NULL DEFAULT '',
    alert_category      TEXT NOT NULL DEFAULT '',
    alert_created_at    TEXT NOT NULL DEFAULT '',
    service_source      TEXT NOT NULL DEFAULT '',
    entities_json       TEXT NOT NULL DEFAULT '[]',
    tier                INTEGER,
    decision            TEXT NOT NULL DEFAULT 'skip',
    action_type         TEXT NOT NULL DEFAULT '',
    job_ids_json        TEXT NOT NULL DEFAULT '[]',
    reason              TEXT NOT NULL DEFAULT '',
    executed_at         TEXT NOT NULL,
    not_before_at       TEXT,
    cancelled           BOOLEAN NOT NULL DEFAULT FALSE,
    cancelled_at        TEXT,
    cancelled_by        TEXT NOT NULL DEFAULT '',
    human_approved      BOOLEAN NOT NULL DEFAULT FALSE,
    approved_at         TEXT,
    approved_by         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_defender_decisions_alert_id
    ON defender_agent_decisions (alert_id);
CREATE INDEX IF NOT EXISTS idx_defender_decisions_executed_at
    ON defender_agent_decisions (executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_defender_decisions_run_id
    ON defender_agent_decisions (run_id, executed_at DESC);
