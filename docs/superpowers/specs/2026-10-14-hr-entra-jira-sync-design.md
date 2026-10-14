# Entra -> Jira HR ticket sync (HRD, LIBTA)

Source mapping: `ADP Jira Mapping v1.xlsx`. Code: `backend/hr_entra_sync.py`, `hr_entra_field_map.py`,
`routes_hr_entra_sync.py`, `hr_jira_field_admin.py`; table `hr_entra_sync_issues` (migration `0034`).

## Behavior
- **Trigger #1 - ticket created.** Every `HR_ENTRA_SYNC_POLL_SECONDS` (60) the leader discovers tickets in
  `HR_ENTRA_SYNC_PROJECTS` (default `HRD,LIBTA`) created within `HR_ENTRA_SYNC_LOOKBACK_MINUTES` (120) and
  registers each once. Other triggers are not defined yet: `HrEntraSyncJob.sync_issue()` is trigger-agnostic.
- **User match.** First email found in `Company email address` (customfield_12879), then `Personal Email Address
  (New Hire)` (customfield_12883). Jira stores these as text or wiki links (`[a@x.com|mailto:a@x.com]`), so the
  first address in the value is extracted. Graph filter: `mail`, `userPrincipalName`, or `otherMails`
  (`ConsistencyLevel: eventual`). More than one match is `ambiguous`: nothing is written.
- **Write.** Entra always overwrites. One PUT; if Jira rejects specific fields (not on the edit screen, unknown
  select option) they are dropped, recorded in `fields_skipped`, and the rest is written.
- **No match.** Retried every poll for `HR_ENTRA_SYNC_RETRY_MINUTES` (15), then one *internal* note
  (`sd.public.comment` property; not visible to the submitter) and status `not_found`. The note is only posted by
  the runner that wins the atomic pending -> terminal update, so blue/green overlap cannot double-post.
- Graph/Jira errors retry inside the window, then status `failed` (no note). Jira 403/404 fails immediately.
- Ships disabled: `HR_ENTRA_SYNC_ENABLED=false`.

## Field mapping status
Only rows that are `enabled` **and** have a `jira_field_id` are written (`active_mappings()`).
- Disabled, source undefined in the sheet: Associate ID, Company email address, Hire Date, Worker Category,
  Job Class, Manager Email, Work Arrangement.
- Disabled, needs confirmation: FLSA Status (sheet maps it to `employeeID`), Legal Middle Name (`middleName` is an
  AD attribute, not a Graph v1.0 user property).
- Enabled but waiting on a Jira field: "Create" rows (Preferred Name, Home State, Leadership Level 2/3, People
  Manager, Position Status, Seniority Date). Run `python hr_jira_field_admin.py` (plan) then `--apply`, add the
  fields to the HRD/LIBTA screens, and paste the ids into `FIELD_MAP`.

## Admin API (admin only)
`GET /api/hr-entra-sync/status`, `GET /api/hr-entra-sync/issues`, `POST /api/hr-entra-sync/issues/{key}/run`
(`dry_run=true` by default).
