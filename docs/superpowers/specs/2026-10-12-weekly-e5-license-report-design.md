# Weekly E5 license reclaim report — design

**Goal:** Email the SPE_E5 license reclaim workbook (same shape as `e5_license_reclaim_candidates_2026-10-12.xlsx`) to Grant Allison and Wayne Berry every Sunday, so reclaim candidates are reviewed on a regular cadence instead of ad hoc.

**Audience / recipients:** `gallison@librasolutionsgroup.com`, `wberry@librasolutionsgroup.com` (Wayne's regular account, not the `ca-`/`sa-` admin accounts), `smetcalf@librasolutionsgroup.com` (Scott Metcalf, added 2026-10-26). Configured via `E5_REPORT_RECIPIENTS`, not hardcoded.

**Scope:** primary site scope's tenant (same Entra app registration the backend already uses). Read-only: nothing is reclaimed automatically.

## Components
1. `backend/e5_license_report.py`
   - Fetch `/subscribedSkus` (seats purchased / consumed for `SPE_E5`) and `/users` with `signInActivity` (latest of interactive and non-interactive), via the existing app-only Graph token.
   - Bucket E5-licensed users: Disabled; Enabled - never signed in; Enabled - idle >90d; Enabled - idle 60-90d. Enabled users active within 60 days are excluded (count shown on Summary).
   - Flag likely non-person accounts (rooms, test, migration, marketing dev, service accounts) as in the existing workbook.
   - Build a two-sheet workbook with openpyxl: `Summary` (COUNTIF formulas over the accounts sheet, seats, guidance text) and `E5 Accounts` (display name, UPN, enabled, last sign-in, days since, created, synced from AD, status, flag).
   - Caveat text retained: signInActivity can lag; treat as leads, not proof.
2. `backend/email_service.py`: `send_email(..., attachments=None)`; each attachment is `{name, content_type, content_bytes}` sent as a Graph `fileAttachment`. Existing callers unchanged.
3. Weekly worker (same file or `e5_license_report_service.py`, mirroring `security_digest_service.py`)
   - Fires Sunday 13:00 UTC (about 8-9am US Central, 9-10am Eastern); day/hour constants configurable.
   - Registered in `main.py` as a leader-only background service.
   - Email: short HTML summary (candidate counts by bucket, seats consumed vs purchased) plus the xlsx attached; filename `e5_license_reclaim_candidates_YYYY-MM-DD.xlsx`; sent from the default `it-ai@` mailbox.
4. Config: `E5_REPORT_ENABLED` (default off until verified), `E5_REPORT_RECIPIENTS`, `E5_REPORT_WEEKDAY`, `E5_REPORT_HOUR`.

## Safety / error handling
- Durable last-sent marker (existing runtime-state store) so restarts and blue/green cutovers do not double-send.
- Graph fetch failure or empty user result: log and skip the send; never email a partial/empty report as if complete. Retry next loop tick within the same day.
- `send_email` returns False on failure: marker is only written on success.
- One small table, `e5_license_report_runs` (migration `0033`), holds the already-sent marker; the repo has no generic key-value store.

## Testing
- Unit: bucketing and day thresholds, non-person flagging, workbook sheets/formulas.
- Job: mocked Graph produces expected workbook; failure paths skip the send and leave the marker unset.
- Schedule: next-fire computation lands on the correct Sunday 13:00 UTC; duplicate-send guard.
- `send_email` attachment payload shape.

## Out of scope
Automatic license removal, UI surface, other SKUs.
