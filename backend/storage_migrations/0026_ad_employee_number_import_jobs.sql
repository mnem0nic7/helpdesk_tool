CREATE TABLE IF NOT EXISTS ad_employee_number_import_jobs (
    job_id              TEXT PRIMARY KEY,
    requested_by        TEXT NOT NULL DEFAULT '',
    filename             TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'queued',
    total_rows           INTEGER NOT NULL DEFAULT 0,
    update_count         INTEGER NOT NULL DEFAULT 0,
    no_change_count      INTEGER NOT NULL DEFAULT 0,
    not_found_count      INTEGER NOT NULL DEFAULT 0,
    skipped_count        INTEGER NOT NULL DEFAULT 0,
    applied_count        INTEGER NOT NULL DEFAULT 0,
    apply_failed_count   INTEGER NOT NULL DEFAULT 0,
    error                TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    completed_at         TEXT
);

CREATE TABLE IF NOT EXISTS ad_employee_number_import_rows (
    id                       TEXT PRIMARY KEY,
    job_id                   TEXT NOT NULL,
    row_index                INTEGER NOT NULL,
    source_email             TEXT NOT NULL DEFAULT '',
    ad_sam                   TEXT NOT NULL DEFAULT '',
    ad_display_name          TEXT NOT NULL DEFAULT '',
    current_employee_number  TEXT NOT NULL DEFAULT '',
    new_employee_number      TEXT NOT NULL DEFAULT '',
    action                   TEXT NOT NULL DEFAULT '',
    applied                  SMALLINT NOT NULL DEFAULT 0,
    apply_error              TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ad_emp_num_jobs_created ON ad_employee_number_import_jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ad_emp_num_rows_job_action ON ad_employee_number_import_rows (job_id, action);
