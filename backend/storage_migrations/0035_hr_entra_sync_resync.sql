ALTER TABLE hr_entra_sync_issues ADD COLUMN IF NOT EXISTS lookup_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE hr_entra_sync_issues ADD COLUMN IF NOT EXISTS email_source TEXT NOT NULL DEFAULT '';
