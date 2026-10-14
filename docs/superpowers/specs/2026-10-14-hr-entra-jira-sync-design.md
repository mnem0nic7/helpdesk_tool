# Entra -> Jira HR ticket sync (HRD, LIBTA)

Source mapping: `ADP Jira Mapping v1.xlsx`. Code: `backend/hr_entra_sync.py`, `hr_entra_field_map.py`,
`routes_hr_entra_sync.py`, `hr_jira_field_admin.py`; table `hr_entra_sync_issues` (migration `0034`).

## Behavior
- **Trigger #1 - ticket created.** Every `HR_ENTRA_SYNC_POLL_SECONDS` (60) the leader discovers tickets in
  `HR_ENTRA_SYNC_PROJECTS` (default `HRD,LIBTA`) created within `HR_ENTRA_SYNC_LOOKBACK_MINUTES` (120) and
  registers each once. Other triggers are not defined yet: `HrEntraSyncJob.sync_issue()` is trigger-agnostic.
- **User match.** First email found in `Company email address` (customfield_12879), then `Personal Email Address
  (New Hire)` (customfield_12883), then - for every request type - the **reporter's** email if the reporter is a person
  (`customer`/`atlassian` account type; apps, null reporters, the AskHR/Benefits mailboxes and service-style names such as
  payroll/donotreply/svc are ignored) and resolves to an *enabled, member, non-service-style* Entra account.
  A reporter is only a guess at the subject, so a reporter-only ticket with no Entra match ends `not_found` with **no
  note** (e.g. DocuSign/ADP notification senders). Which source matched is stored in `email_source`. Jira stores these as text or wiki links (`[a@x.com|mailto:a@x.com]`), so the
  first address in the value is extracted. Graph filter: `mail`, `userPrincipalName`, or `otherMails`
  (`ConsistencyLevel: eventual`). More than one match is `ambiguous`: nothing is written.
- **Trigger #2 - email edited.** Each cycle the job also looks at tickets `updated` within the lookback window. A
  registered ticket whose work/personal emails differ from `lookup_fingerprint` (the emails it was last processed with)
  is reopened as `pending` with a fresh 15-minute window; an unregistered older ticket is picked up only if its changelog
  shows a real edit to either email field. Jira's `changed` JQL operator is not usable on this site, hence the
  fingerprint + changelog approach. Migration `0035` adds `lookup_fingerprint` and `email_source`.
- **Write.** Entra always overwrites. One PUT; if Jira rejects specific fields (not on the edit screen, unknown
  select option) they are dropped, recorded in `fields_skipped`, and the rest is written.
- **No match.** Retried every poll for `HR_ENTRA_SYNC_RETRY_MINUTES` (15), then one *internal* note
  (`sd.public.comment` property; not visible to the submitter) and status `not_found`. The note is only posted by
  the runner that wins the atomic pending -> terminal update, so blue/green overlap cannot double-post.
- Graph/Jira errors retry inside the window, then status `failed` (no note). Jira 403/404 fails immediately.
- Ships disabled: `HR_ENTRA_SYNC_ENABLED=false`.

## Field mapping status
Only rows that are `enabled` **and** have a `jira_field_id` are written (`active_mappings()`) - 16 today:
Business Unit, Preferred Name, Home State, Home Department, Function, Job Title, Leadership Level 2/3, Legal First/Last
Name, Employee location, People Manager, Position ID, Position Status, Manager Name, Seniority Date.
- Disabled, source undefined in the sheet (Jira fields exist, ids 15092-15095 etc.): Associate ID, Company email
  address, Hire Date, Worker Category, Job Class, Manager Email, Work Arrangement.
- Disabled, needs confirmation: FLSA Status (sheet maps it to `employeeID`), Legal Middle Name (`middleName` is an
  AD attribute, not a Graph v1.0 user property).

## Jira setup (done 2026-10-14)
`python hr_jira_field_admin.py --apply` renamed 9 fields and created 11 (ids `customfield_15085`-`15095`);
`--screens --apply` added every mapped field to the 7 HRD screens (12223-12229) and LIBTA's edit/view screens
(12275, 12533), and Company email address to LIBTA's create screen (12274). Both modes are idempotent.
Still manual: option lists for Function and Worker Category (the sheet gives no target values).

## LIBTA write access (resolved 2026-10-14)
LIBTA uses the shared *Default Permission Scheme* (also OASIS and PAYR), and the Jira service account ("IT AI atlassian")
had no Edit Issues there. It was added to the **Developers** project role in LIBTA only (role membership is per
project, so OASIS/PAYR are unaffected) rather than editing the shared scheme. Do not add a user grant to the Default
scheme for this account: that would extend its edit rights to PAYR/OASIS.

## Status page
`hrapp.movedocs.com/entra-sync` (`frontend/src/pages/HrEntraSyncPage.tsx`, nav entry "Entra → Jira Sync"): enabled/running/failed
banner, counts by outcome, config summary, recent tickets (filterable), the field-mapping table with why each disabled row
is off, and a dry-run tester. The tester accepts an optional email that replaces the ticket's own (dry run only, enforced
server-side) so any live ticket can be tested.

## Data-quality notes (Entra, 2026-10-14)
- Function: Entra says "Information Technology"/"Human Resources" -> aliased to Jira's IT/HR. "Exec/Admin" (20 users) has no
  Jira option; Jira rejects it per field and the field is skipped. Add the option in Jira or decide an alias.
- 3 accounts carry ADP header text (`JobFunction`, `JobFunctionDescription`) as their value; treated as empty.
- 1054 of 1686 enabled accounts have no jobFunction at all, so many fields will legitimately be left unwritten.

## Admin API (admin only)
`GET /api/hr-entra-sync/status`, `GET /api/hr-entra-sync/issues`, `POST /api/hr-entra-sync/issues/{key}/run`
(`dry_run=true` by default).
