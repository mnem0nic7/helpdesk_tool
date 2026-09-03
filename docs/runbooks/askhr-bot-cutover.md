# AskHR/Benefits bot — enablement prerequisites and legacy transport rule cutover

This doc covers two separate manual phases:

1. **Enablement prerequisites** — what must be true *before* the bot is
   enabled at all (below).
2. **Legacy transport rule cutover** — disabling the four Bcc-forwarding
   transport rules, done only *after* the bot has run and been verified
   end-to-end (further down).

---

## Enablement Prerequisites

Do all of these before flipping the bot on at `/askhr-bot` on
`hrapp.movedocs.com`. None of them are performed by code — they are tenant
and Jira configuration that the app assumes already exists.

### 1. Entra redirect URI for the new host

Register

```
https://hrapp.movedocs.com/api/auth/callback
```

as a valid redirect URI on the Entra app registration used for Entra SSO
login (the same registration the `azure.movedocs.com` /
`security.movedocs.com` hosts already use). Without it, every sign-in
attempt on the new host fails with **AADSTS50011 (redirect URI mismatch)**
— the app itself will look completely broken, not merely misconfigured.

### 2. DNS for `hrapp.movedocs.com`

`hrapp.movedocs.com` must resolve to the same infrastructure as the other
four hosts *before* deploy. The host is only appended to the existing
shared Caddy site block — Caddy's TLS issuer cannot obtain a certificate
for a name that does not resolve, so a missing DNS record shows up as a TLS
failure on the new host (and repeated ACME retries in the Caddy logs) while
the other four hosts keep working.

### 3. Microsoft Graph `Mail.Read` application permission

The bot reads both mailboxes with the shared Entra app registration already
used for ARM/Graph/Exchange elsewhere in this app (`ENTRA_CLIENT_ID` /
`ENTRA_CLIENT_SECRET` / `ENTRA_TENANT_ID`) — there are no new secrets. That
registration needs the **tenant-wide `Mail.Read` *application* permission**
(not delegated), **admin-consented**. Per the design decision, the grant is
intentionally *not* narrowed with an Application Access Policy, so it grants
read access to all mailboxes in the tenant.

Until consent is granted, every poll cycle fails with a Graph 403 and no
tickets are created.

### 4. Verify the HRD issue-type names used by the classic-reporter fallback

`backend/askhr_bot_job.py` has two hardcoded issue-type names used **only**
on the `classic_reporter_field` fallback path (taken when
`raiseOnBehalfOf` returns 400/403 and the bot caches the classic reporter
mode instead):

| Mailbox | Hardcoded issue type |
|---|---|
| `AskHR@librasolutionsgroup.com` | `Emailed request` |
| `Benefits@librasolutionsgroup.com` | `Benefits` |

**These names have never been verified against the live HRD project.** If
`raiseOnBehalfOf` ever falls back to this path and either name does not
exist as an issue type in project `HRD`, that mailbox's tickets fail with a
400 from Jira (recorded as `failed` rows on the `/askhr-bot` messages
table, retryable — but nothing gets filed until the name is fixed).

Before enabling, an operator with Jira access must confirm **both** names
exist as issue types in project `HRD`, via either:

- `GET /rest/api/2/issue/createmeta?projectKeys=HRD&expand=projects.issuetypes`
  (check `projects[0].issuetypes[].name`), or
- the JSM project admin UI → **Project settings → Issue types**.

Record the confirmation here when done:

> Issue-type names confirmed in project HRD on ____________ by
> ____________ (`Emailed request`: ☐ present, `Benefits`: ☐ present). If
> either name differs, update the corresponding literal in
> `backend/askhr_bot_job.py`'s `_create_ticket()` before enabling.

### 5. Spot-check the other hardcoded Jira constants

Also in `backend/askhr_bot_job.py`, confirm each of these is still correct
in the target Jira instance before the first enable:

| Constant | Value | How to check |
|---|---|---|
| `JSM_PROJECT_KEY` | `HRD` | Project key of the HR service desk. |
| `JSM_SERVICE_DESK_ID` | `73` | `GET /rest/servicedeskapi/servicedesk` → match `projectKey: HRD` to its `id`. |
| `MAILBOXES["askhr"]["request_type_id"]` | `420` | `GET /rest/servicedeskapi/servicedesk/73/requesttype`. |
| `MAILBOXES["benefits"]["request_type_id"]` | `619` | Same call as above. |
| `REPORTER_ACCOUNT_IDS["askhr"]` | `qm:…:9528d568-…` | The AskHR customer account that must appear as reporter. |
| `REPORTER_ACCOUNT_IDS["benefits"]` | `qm:…:5f896e59-…` | The Benefits customer account. |

A wrong service-desk id or request-type id fails every ticket on the
`raiseOnBehalfOf` path; a wrong reporter account id files tickets under the
wrong customer, which is worse than failing because it succeeds silently.

### 6. Sanity checks after enabling, before the cutover below

- Watch `/askhr-bot` for the first couple of cycles: run rows should appear
  for both mailboxes, and `reporter_mode` should settle on
  `raise_on_behalf_of` (or `classic_reporter_field` if the probe fell back —
  in which case #4 above is now load-bearing, not hypothetical).
- Confirm **trusted domains** shows a non-zero count with a recent
  refreshed-at. A zero count with a stale timestamp means the
  `Get-TransportRule` refresh is failing; the bot deliberately keeps the last
  known-good list and retries rather than treating "no domains" as "nothing
  is trusted".
- Note that the legacy transport rules are still active at this point, so
  each qualifying email produces **both** a Bcc-forwarded ticket and a
  bot-created ticket. That duplication is expected until the cutover below.

---

## Legacy transport rule cutover

**Do this manually, once, after the AskHR bot has been enabled and verified end-to-end.**
No code path in this repo performs this step — it is a deliberate one-time,
human-triggered action because disabling mail routing is high blast-radius
and hard to reverse quickly if something is wrong.

## Prerequisites

- The AskHR bot (`/askhr-bot` on `hrapp.movedocs.com`) has been enabled for
  at least a few days.
- You have spot-checked that tickets created by the bot in HRD look correct:
  reporter is AskHR/Benefits (not the original sender), the original email
  is attached as `.eml`, and the description includes the original
  sender/date/body.
- You have compared bot-created ticket volume against historical Bcc-forwarded
  ticket volume for the same mailboxes over a comparable period, and they're
  consistent.

## Steps

Connect to Exchange Online PowerShell with an account that can manage
transport rules, then run:

```powershell
Disable-TransportRule -Identity "Forward External Mail to Jira - AskHR" -Confirm:$false
Disable-TransportRule -Identity "Forward Payroll Mail to Jira - AskHR" -Confirm:$false
Disable-TransportRule -Identity "Forward External Mail to Jira - Benefits" -Confirm:$false
Disable-TransportRule -Identity "Forward Payroll Mail to Jira - Benefits" -Confirm:$false
```

Verify each rule shows `State: Disabled` (not deleted — keep them in place
in case you need to re-enable quickly):

```powershell
Get-TransportRule -Identity "Forward External Mail to Jira - AskHR" | Select-Object Name, State
Get-TransportRule -Identity "Forward Payroll Mail to Jira - AskHR" | Select-Object Name, State
Get-TransportRule -Identity "Forward External Mail to Jira - Benefits" | Select-Object Name, State
Get-TransportRule -Identity "Forward Payroll Mail to Jira - Benefits" | Select-Object Name, State
```

## Rollback

Re-enable any rule with `Enable-TransportRule -Identity "<name>"` if the bot
needs to be disabled and mail-flow forwarding restored while you investigate.
