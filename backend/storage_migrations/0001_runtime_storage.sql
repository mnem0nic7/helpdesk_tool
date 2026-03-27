CREATE TABLE IF NOT EXISTS runtime_leader_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    desired_leader_color TEXT NOT NULL DEFAULT '',
    lease_owner_color TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

INSERT INTO runtime_leader_state (
    singleton_id, desired_leader_color, lease_owner_color, lease_expires_at, updated_at
) VALUES (1, '', '', '', NOW()::text)
ON CONFLICT(singleton_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    auth_provider TEXT,
    is_admin INTEGER,
    can_manage_users INTEGER,
    site_scope TEXT
);

CREATE TABLE IF NOT EXISTS atlassian_connections (
    email TEXT PRIMARY KEY,
    atlassian_account_id TEXT NOT NULL,
    atlassian_account_name TEXT NOT NULL,
    cloud_id TEXT NOT NULL,
    site_url TEXT NOT NULL,
    scope TEXT NOT NULL,
    access_token_encrypted TEXT NOT NULL,
    refresh_token_encrypted TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_audit (
    event_id BIGSERIAL PRIMARY KEY,
    sid TEXT NOT NULL,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    auth_provider TEXT NOT NULL,
    site_scope TEXT NOT NULL,
    source_ip TEXT NOT NULL,
    user_agent TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_audit_created
    ON login_audit (created_at DESC);

CREATE TABLE IF NOT EXISTS report_templates (
    id TEXT PRIMARY KEY,
    seed_key TEXT UNIQUE,
    site_scope TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    readiness TEXT NOT NULL DEFAULT 'custom',
    is_seed INTEGER NOT NULL DEFAULT 0,
    include_in_master_export INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL,
    created_by_email TEXT NOT NULL DEFAULT '',
    created_by_name TEXT NOT NULL DEFAULT '',
    updated_by_email TEXT NOT NULL DEFAULT '',
    updated_by_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(site_scope, name)
);

CREATE TABLE IF NOT EXISTS deleted_seed_keys (
    seed_key TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_report_templates_scope
    ON report_templates(site_scope, category, name);

CREATE TABLE IF NOT EXISTS report_ai_summaries (
    site_scope TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_name TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    summary TEXT NOT NULL DEFAULT '',
    bullets_json TEXT NOT NULL DEFAULT '[]',
    fallback_used INTEGER NOT NULL DEFAULT 0,
    model_used TEXT NOT NULL DEFAULT '',
    generated_at TEXT,
    template_version TEXT NOT NULL DEFAULT '',
    data_version TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_scope, template_id, source)
);

CREATE TABLE IF NOT EXISTS report_ai_summary_batches (
    batch_id TEXT PRIMARY KEY,
    site_scope TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    requested_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS report_ai_summary_batch_items (
    batch_id TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_name TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'queued',
    summary TEXT NOT NULL DEFAULT '',
    bullets_json TEXT NOT NULL DEFAULT '[]',
    fallback_used INTEGER NOT NULL DEFAULT 0,
    model_used TEXT NOT NULL DEFAULT '',
    generated_at TEXT,
    error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (batch_id, template_id)
);

CREATE TABLE IF NOT EXISTS directory_emails (
    email_key TEXT NOT NULL,
    entra_user_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    canonical_email TEXT NOT NULL DEFAULT '',
    account_class TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (email_key, entra_user_id, source_kind)
);

CREATE TABLE IF NOT EXISTS jira_requestor_links (
    email_key TEXT NOT NULL DEFAULT '',
    ticket_key TEXT NOT NULL,
    extracted_email TEXT NOT NULL DEFAULT '',
    directory_user_id TEXT NOT NULL DEFAULT '',
    directory_display_name TEXT NOT NULL DEFAULT '',
    canonical_email TEXT NOT NULL DEFAULT '',
    jira_account_id TEXT NOT NULL DEFAULT '',
    jira_display_name TEXT NOT NULL DEFAULT '',
    match_source TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (email_key, ticket_key)
);

CREATE INDEX IF NOT EXISTS idx_directory_emails_key
    ON directory_emails (email_key, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_requestor_links_ticket
    ON jira_requestor_links (ticket_key, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_requestor_links_email
    ON jira_requestor_links (email_key, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_requestor_links_status
    ON jira_requestor_links (sync_status, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS triage_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS triage_suggestions (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    model TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS triage_auto_triaged (
    key TEXT PRIMARY KEY,
    processed_at TEXT,
    priority_updated INTEGER DEFAULT 0,
    request_type_updated INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS triage_auto_triage_log (
    id BIGSERIAL PRIMARY KEY,
    key TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    confidence DOUBLE PRECISION,
    model TEXT,
    source TEXT NOT NULL DEFAULT 'auto',
    approved_by TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS triage_technician_scores (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    model TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_triage_log_timestamp
    ON triage_auto_triage_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_suggestions_updated_at
    ON triage_suggestions(updated_at);

CREATE TABLE IF NOT EXISTS alert_rules (
    id BIGSERIAL PRIMARY KEY,
    site_scope TEXT NOT NULL DEFAULT 'primary',
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    trigger_type TEXT NOT NULL,
    trigger_config TEXT NOT NULL DEFAULT '{}',
    frequency TEXT NOT NULL DEFAULT 'daily',
    schedule_time TEXT NOT NULL DEFAULT '08:00',
    schedule_days TEXT NOT NULL DEFAULT '0,1,2,3,4',
    recipients TEXT NOT NULL,
    cc TEXT NOT NULL DEFAULT '',
    filters TEXT NOT NULL DEFAULT '{}',
    last_run TEXT,
    last_sent TEXT,
    created_at TEXT NOT NULL DEFAULT NOW()::text,
    updated_at TEXT NOT NULL DEFAULT NOW()::text,
    custom_subject TEXT NOT NULL DEFAULT '',
    custom_message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alert_history (
    id BIGSERIAL PRIMARY KEY,
    site_scope TEXT NOT NULL DEFAULT 'primary',
    rule_id BIGINT NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
    rule_name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT NOW()::text,
    recipients TEXT NOT NULL,
    ticket_count INTEGER NOT NULL DEFAULT 0,
    ticket_keys TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'sent',
    error TEXT
);

CREATE TABLE IF NOT EXISTS alert_seen_tickets (
    rule_id BIGINT NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
    ticket_key TEXT NOT NULL,
    seen_at TEXT NOT NULL DEFAULT NOW()::text,
    PRIMARY KEY (rule_id, ticket_key)
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_scope_enabled
    ON alert_rules(site_scope, enabled);
CREATE INDEX IF NOT EXISTS idx_alert_history_rule_scope_sent
    ON alert_history(rule_id, site_scope, sent_at);
CREATE INDEX IF NOT EXISTS idx_alert_history_scope_sent
    ON alert_history(site_scope, sent_at);

CREATE TABLE IF NOT EXISTS azure_alert_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    domain TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_config TEXT NOT NULL DEFAULT '{}',
    frequency TEXT NOT NULL,
    schedule_time TEXT NOT NULL DEFAULT '09:00',
    schedule_days TEXT NOT NULL DEFAULT '0,1,2,3,4',
    recipients TEXT NOT NULL DEFAULT '',
    teams_webhook_url TEXT NOT NULL DEFAULT '',
    custom_subject TEXT NOT NULL DEFAULT '',
    custom_message TEXT NOT NULL DEFAULT '',
    last_run TEXT,
    last_sent TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_azure_alert_rules_domain_enabled
    ON azure_alert_rules(domain, enabled);

CREATE TABLE IF NOT EXISTS azure_alert_history (
    id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL REFERENCES azure_alert_rules(id) ON DELETE CASCADE,
    rule_name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    recipients TEXT NOT NULL,
    match_count INTEGER NOT NULL DEFAULT 0,
    match_summary TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_azure_alert_history_rule_sent
    ON azure_alert_history(rule_id, sent_at);

CREATE TABLE IF NOT EXISTS azure_alert_vm_states (
    vm_id TEXT PRIMARY KEY,
    first_seen_deallocated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS azure_alert_user_states (
    user_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sla_targets (
    id BIGSERIAL PRIMARY KEY,
    sla_type TEXT NOT NULL,
    dimension TEXT NOT NULL DEFAULT 'default',
    dimension_value TEXT NOT NULL DEFAULT '*',
    target_minutes INTEGER NOT NULL,
    UNIQUE(sla_type, dimension, dimension_value)
);

CREATE TABLE IF NOT EXISTS sla_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_articles (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    request_type TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    source_filename TEXT NOT NULL DEFAULT '',
    source_ticket_key TEXT NOT NULL DEFAULT '',
    imported_from_seed INTEGER NOT NULL DEFAULT 0,
    ai_generated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kb_articles_request_type
    ON kb_articles(request_type);
CREATE INDEX IF NOT EXISTS idx_kb_articles_slug
    ON kb_articles(slug);

CREATE TABLE IF NOT EXISTS export_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    requester_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    lookback_days INTEGER NOT NULL,
    filters_json TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT NOT NULL DEFAULT '',
    file_name TEXT,
    file_path TEXT,
    file_size INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    notified_at TEXT,
    notification_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_export_jobs_status_requested_at
    ON export_jobs(status, requested_at);

CREATE TABLE IF NOT EXISTS export_deliveries (
    delivery_id TEXT PRIMARY KEY,
    dataset TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    delivery_date TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    delivery_key TEXT NOT NULL UNIQUE,
    landing_path TEXT NOT NULL UNIQUE,
    manifest_path TEXT NOT NULL DEFAULT '',
    parse_status TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    parsed_at TEXT,
    error_message TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    source_etag TEXT,
    source_size_bytes INTEGER NOT NULL DEFAULT 0,
    parser_version TEXT NOT NULL DEFAULT '',
    schema_signature TEXT NOT NULL DEFAULT '',
    schema_compatible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_export_deliveries_dataset_scope
    ON export_deliveries(dataset, scope_key);
CREATE INDEX IF NOT EXISTS idx_export_deliveries_status
    ON export_deliveries(parse_status);

CREATE TABLE IF NOT EXISTS export_stage_models (
    delivery_key TEXT PRIMARY KEY,
    stage_model_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_quarantine (
    delivery_key TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL,
    content TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_exit_workflows (
    workflow_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_display_name TEXT NOT NULL DEFAULT '',
    user_principal_name TEXT NOT NULL DEFAULT '',
    requested_by_email TEXT NOT NULL,
    requested_by_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    profile_key TEXT NOT NULL DEFAULT '',
    on_prem_required INTEGER NOT NULL DEFAULT 0,
    requires_on_prem_username_override INTEGER NOT NULL DEFAULT 0,
    on_prem_sam_account_name TEXT NOT NULL DEFAULT '',
    on_prem_distinguished_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_user_exit_workflows_user
    ON user_exit_workflows(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_exit_steps (
    step_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES user_exit_workflows(workflow_id) ON DELETE CASCADE,
    step_key TEXT NOT NULL,
    label TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    profile_key TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    before_summary_json TEXT NOT NULL DEFAULT '{}',
    after_summary_json TEXT NOT NULL DEFAULT '{}',
    assigned_agent_id TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT,
    heartbeat_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_user_exit_steps_workflow
    ON user_exit_steps(workflow_id, order_index);

CREATE TABLE IF NOT EXISTS user_exit_manual_tasks (
    task_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES user_exit_workflows(workflow_id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    completed_by_email TEXT NOT NULL DEFAULT '',
    completed_by_name TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_user_exit_manual_tasks_workflow
    ON user_exit_manual_tasks(workflow_id, created_at);

CREATE TABLE IF NOT EXISTS onedrive_copy_jobs (
    job_id TEXT PRIMARY KEY,
    site_scope TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    requested_by_email TEXT NOT NULL,
    requested_by_name TEXT NOT NULL,
    source_upn TEXT NOT NULL,
    destination_upn TEXT NOT NULL,
    destination_folder TEXT NOT NULL,
    test_mode INTEGER NOT NULL DEFAULT 0,
    test_file_limit INTEGER NOT NULL DEFAULT 25,
    exclude_system_folders INTEGER NOT NULL DEFAULT 1,
    requested_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT NOT NULL DEFAULT '',
    total_folders_found INTEGER NOT NULL DEFAULT 0,
    total_files_found INTEGER NOT NULL DEFAULT 0,
    folders_created INTEGER NOT NULL DEFAULT 0,
    files_dispatched INTEGER NOT NULL DEFAULT 0,
    files_failed INTEGER NOT NULL DEFAULT 0,
    source_drive_id TEXT NOT NULL DEFAULT '',
    destination_drive_id TEXT NOT NULL DEFAULT '',
    destination_top_folder_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS onedrive_copy_job_events (
    event_id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES onedrive_copy_jobs(job_id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS onedrive_copy_saved_upns (
    normalized_upn TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    principal_name TEXT NOT NULL DEFAULT '',
    mail TEXT NOT NULL DEFAULT '',
    source_hint TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    last_used_by_email TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_onedrive_copy_jobs_requested_at
    ON onedrive_copy_jobs (requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_onedrive_copy_events_job
    ON onedrive_copy_job_events (job_id, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_onedrive_copy_saved_upns_last_used
    ON onedrive_copy_saved_upns (last_used_at DESC);

CREATE TABLE IF NOT EXISTS user_admin_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    action_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    target_user_ids_json TEXT NOT NULL,
    params_json TEXT NOT NULL,
    requested_by_email TEXT NOT NULL,
    requested_by_name TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT NOT NULL DEFAULT '',
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS user_admin_job_results (
    id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    target_display_name TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    success INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    before_summary_json TEXT NOT NULL DEFAULT '{}',
    after_summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_admin_audit (
    audit_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    actor_email TEXT NOT NULL,
    actor_name TEXT NOT NULL DEFAULT '',
    target_user_id TEXT NOT NULL,
    target_display_name TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    action_type TEXT NOT NULL,
    params_summary_json TEXT NOT NULL DEFAULT '{}',
    before_summary_json TEXT NOT NULL DEFAULT '{}',
    after_summary_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_admin_jobs_status_requested
    ON user_admin_jobs(status, requested_at);
CREATE INDEX IF NOT EXISTS idx_user_admin_job_results_job
    ON user_admin_job_results(job_id, id);
CREATE INDEX IF NOT EXISTS idx_user_admin_audit_target
    ON user_admin_audit(target_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_admin_audit_created
    ON user_admin_audit(created_at DESC);
