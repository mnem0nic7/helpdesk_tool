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
  **Internal-domain rule:** the reporter and the *Company email address* field are only looked up if the address is on a
  domain verified on our Entra tenant (`GET /organization`, `Email` capability, excluding `*.onmicrosoft.com` and relay
  entries; subdomains count; cached 1h; **fails closed** - if the list cannot be loaded the ticket retries instead of
  looking up blindly). The *Personal Email Address (New Hire)* field is exempt because it exists for outside addresses
  (matched via Entra `otherMails`), and the dry-run tester's email override is exempt. An outside-only reporter (vendor or
  notification sender) is never sent to Graph and the ticket ends `not_found` immediately with no note.
  **The reporter is not used where it is not the subject:** Employee offboarding, Status Change, Requisition,
  Employee onboarding and every LIBTA ticket are filed by HR or a manager for someone else (on recent offboarding
  tickets the filer was not the leaver ~58% of the time), so the reporter's profile would be the wrong person's.
  **Offboarding** instead reads the employee from the ticket's JSM Form answer *Employee Work Email* (Forms API,
  `GET api.atlassian.com/jira/forms/cloud/{cloudId}/issue/{key}/form`; 22 of 25 recent tickets have it; subject to the
  internal-domain rule; `email_source = form`). A ticket in a blocked type with no identifiable employee ends `not_found`
  quietly (no note, no write).
  **Status Change** has no email, so the employee is identified by the ticket's **Position ID** (Entra directory
  extension `positionID`, exact), then exact **first + last name** (`givenName`/`surname`); an email on the ticket still
  wins. Only enabled, member, non-service accounts count; more than one match is `ambiguous` (no write). Status Change is
  **fill-only**: HR types the *requested* values (e.g. a new Job Title) and Entra holds the current ones, so existing
  Jira values are never overwritten (`fields_kept`). On 25 recent tickets: 14 matched by Position ID, 4 by name, 3 by
  email, 4 unresolved.
  **Not yet built:** Employee onboarding and Requisition - see open decisions below.
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

## Field order on screens
The sheet's **Order #** (column A of `ADP Jira Mapping v1.xlsx`, mirrored in `hr_entra_field_map.DISPLAY_ORDER`) is the order
the 25 fields appear on the HRD screens (12223-12229) and LIBTA's (12275, 12533; the create screen 12274 holds the 8 it
carries). `python hr_jira_field_admin.py --order [--apply]` makes them one contiguous block in that order, placed where the
earliest of them already sat, leaving every other field in its existing relative order; it only moves fields within their
tab and re-running is a no-op. Applied 2026-10-14. The pre-change layouts are saved in
`data/hr_entra_sync_rollbacks/screen-layout-before-20261014.json`; `--restore-order <file> [--apply]` puts them back.
This orders the create/edit/transition screens; the issue view's Details panel is governed by Project settings -> Issue
layout, which Jira has no public API for.

## Auto-cancel by sender domain
`backend/hr_auto_cancel.py` (+ `routes_hr_auto_cancel.py`, migration `0036`, table `hr_auto_cancel_actions`): a separate
leader-only job that sets new HRD/LIBTA tickets from a listed sender domain to **Cancelled by HR**. Settings:
`HR_AUTO_CANCEL_ENABLED`, `_PROJECTS` (HRD,LIBTA), `_SENDER_DOMAINS` (osidigital.com; subdomains match, lookalikes do not),
`_STATUS`, `_POLL_SECONDS` (60), `_LOOKBACK_MINUTES` (120).
- Candidates: created in the lookback window **and still in a "To Do" status category** (a ticket a human already moved is
  never touched); the sender is the reporter's email (the creator's if the reporter's is hidden).
- Action: the project's transition whose *target status* is "Cancelled by HR" (no required fields; present from New Request),
  then one **internal** note saying why and how to undo it. A project whose workflow has no such status (LIBTA today:
  only "Offer Declined") is recorded `no_transition` and left alone.
- **Once only**: the ledger row is claimed before acting, so a ticket someone reopens is never cancelled again and a
  blue/green overlap cannot act twice. A failed transition is retried (max 5 attempts) while the ticket is in the window.
- No backfill: only tickets created inside the lookback window are considered. As of 2026-10-14 `HRD-1410` (an L&D request
  from a person at osidigital.com, open since 2026-09-14) is outside it and untouched.
- Admin API: `GET /api/hr-auto-cancel/status|actions|preview` (preview is read-only). Shown on the hrapp status page.

## Status page
`hrapp.movedocs.com/entra-sync` (`frontend/src/pages/HrEntraSyncPage.tsx`, nav entry "Entra → Jira Sync"): enabled/running/failed
banner, counts by outcome, config summary, recent tickets (filterable), the field-mapping table with why each disabled row
is off, and a dry-run tester. The tester accepts an optional email that replaces the ticket's own (dry run only, enforced
server-side) so any live ticket can be tested.

## Data-quality notes (Entra, 2026-10-14)
- Function: Entra says "Information Technology"/"Human Resources" -> aliased to Jira's IT/HR. "Exec/Admin" (20 users) had no
  Jira option, so Jira rejected it per field; the option was added to Function (context 12027) on 2026-10-14.
- 3 accounts carry ADP header text (`JobFunction`, `JobFunctionDescription`) as their value; treated as empty.
- 1054 of 1686 enabled accounts have no jobFunction at all, so many fields will legitimately be left unwritten.

## Real runs and rollback
`backend/hr_entra_sync_rollback.py` snapshots a ticket's mapped fields before a real run and restores them on request
(`python hr_entra_sync_rollback.py <snapshot.json>` plans, `--apply` restores). It only reverts a field that still holds the
value the sync wrote, so a person's later edit is never undone (`--force` overrides). Snapshots hold employee data and live
in `data/hr_entra_sync_rollbacks/` (git-ignored, mode 600); also record connector settings and the git SHA in effect.
- 2026-10-14: first real run on **HRD-2163** (open General Inquiry, matched via reporter fallback, 15 fields filled,
  nothing overwritten). Snapshot: `data/hr_entra_sync_rollbacks/HRD-2163-20261014T162819Z.json`.

## Admin API (admin only)
`GET /api/hr-entra-sync/status`, `GET /api/hr-entra-sync/issues`, `POST /api/hr-entra-sync/issues/{key}/run`
(`dry_run=true` by default).


## Open decisions (2026-10-14)
- **Requisition**: the Headcount Request Form's "Email Address" (24/25) - whose is it and is an Entra lookup wanted?
  Currently no lookup and no write.
- **Employee onboarding**: new hires are usually not in Entra yet; sparse identifying data on the ticket (personal email
  field is honoured when present). Currently no reporter fallback.
