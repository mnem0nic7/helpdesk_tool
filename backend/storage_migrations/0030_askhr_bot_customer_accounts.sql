CREATE TABLE IF NOT EXISTS askhr_bot_customer_accounts (
    sender_email    TEXT PRIMARY KEY,
    jira_account_id TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
