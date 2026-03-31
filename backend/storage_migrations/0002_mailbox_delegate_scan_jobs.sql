CREATE TABLE IF NOT EXISTS mailbox_delegate_scan_jobs (
    job_id TEXT PRIMARY KEY,
    site_scope TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    requested_by_email TEXT NOT NULL,
    requested_by_name TEXT NOT NULL,
    user_identifier TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    principal_name TEXT NOT NULL DEFAULT '',
    primary_address TEXT NOT NULL DEFAULT '',
    provider_enabled INTEGER NOT NULL DEFAULT 0,
    supported_permission_types_json TEXT NOT NULL DEFAULT '[]',
    permission_counts_json TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    mailbox_count INTEGER NOT NULL DEFAULT 0,
    scanned_mailbox_count INTEGER NOT NULL DEFAULT 0,
    mailboxes_json TEXT NOT NULL DEFAULT '[]',
    requested_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mailbox_delegate_scan_job_events (
    event_id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES mailbox_delegate_scan_jobs(job_id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mailbox_delegate_scan_jobs_requested
    ON mailbox_delegate_scan_jobs (requested_by_email, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_mailbox_delegate_scan_jobs_status
    ON mailbox_delegate_scan_jobs (status, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_mailbox_delegate_scan_job_events_job
    ON mailbox_delegate_scan_job_events (job_id, event_id DESC);
