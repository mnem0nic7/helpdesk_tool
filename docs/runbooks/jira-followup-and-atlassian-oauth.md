# Jira Follow-Up Signal and Atlassian OAuth Runbook

This runbook covers the two linked setup tasks behind the `2-Hour Response & Daily Follow-Up` report and real-user Jira authorship from MoveDocs.

## 1. Jira Custom Fields for Daily Public Follow-Up

Create these Jira custom fields in the OIT project:

1. `Last Public Agent Touch At`
   Type: Date Time
2. `Public Agent Touch Count`
   Type: Number
3. `Daily Public Follow-Up Status`
   Type: Single select
   Allowed values: `Running`, `Met`, `BREACHED`
4. `Daily Public Follow-Up Breached At`
   Type: Date Time

Put the resulting field IDs in `backend/.env`:

```env
JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID=customfield_12345
JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID=customfield_12346
JIRA_FOLLOWUP_STATUS_FIELD_ID=customfield_12347
JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID=customfield_12348
JIRA_FOLLOWUP_AGENT_GROUPS=oit-agents,jsm-servicedesk-team
```

## 2. Jira Automation Rules

Use project `OIT`.

### Rule A: Initialize Follow-Up Tracking

Trigger:
- Issue created
- Issue transitioned from a done state back to an open state

Actions:
- Clear `Last Public Agent Touch At`
- Set `Public Agent Touch Count` to `0`
- Clear `Daily Public Follow-Up Breached At`
- Set `Daily Public Follow-Up Status` to `Running`

### Rule B: Record Public Agent Touch

Trigger:
- Comment added

Conditions:
- Comment is public
- Comment author is in one of the configured `JIRA_FOLLOWUP_AGENT_GROUPS`

Actions:
- Set `Last Public Agent Touch At` to `{{comment.created}}`
- Increment `Public Agent Touch Count`
- If `Daily Public Follow-Up Status` is not `BREACHED`, keep/set it to `Running`

### Rule C: Scheduled Breach Check

Trigger:
- Scheduled hourly

Scope:
- unresolved OIT issues
- `Last Public Agent Touch At` is not empty
- `Daily Public Follow-Up Status` is not `BREACHED`
- `{{now.diff(issue.Last Public Agent Touch At).hours}} >= 24`

Actions:
- Set `Daily Public Follow-Up Status` to `BREACHED`
- Set `Daily Public Follow-Up Breached At` to `{{now}}`

### Rule D: Finalize on Resolution

Trigger:
- Issue transitioned to a done state

Logic:
- If `Daily Public Follow-Up Status` is already `BREACHED`, leave it
- Else if `Last Public Agent Touch At` is empty, set status to `BREACHED`
- Else set status to `Met`

## 3. Historical Backfill

After the fields and automation rules are live, backfill the last 60 days:

```bash
python backend/scripts/backfill_followup_fields.py --days 60
python backend/scripts/backfill_followup_fields.py --days 60 --write
```

Then refresh the issue cache and verify the report template flips from `proxy` to `ready`.

## 4. Atlassian OAuth 2.0 (3LO) for Jira Writes

MoveDocs can now post Jira writes as the connected human Jira user instead of the shared `it-app` account.

### Atlassian Developer Console

1. Create a new OAuth 2.0 (3LO) app.
2. Add callback URLs for each MoveDocs origin:
   - `https://it-app.movedocs.com/api/auth/atlassian/callback`
   - `https://oasisdev.movedocs.com/api/auth/atlassian/callback`
   - `https://azure.movedocs.com/api/auth/atlassian/callback`
3. Add these scopes:
   - `offline_access`
   - `read:jira-user`
   - `read:jira-work`
   - `write:jira-work`
   - `read:servicedesk-request`
   - `write:servicedesk-request`
4. Set the allowed Jira site URL to the tenant this app should use.

### Backend Environment

Add to `backend/.env`:

```env
ATLASSIAN_CLIENT_ID=...
ATLASSIAN_CLIENT_SECRET=...
ATLASSIAN_ALLOWED_SITE_URL=https://your-instance.atlassian.net
ATLASSIAN_TOKEN_ENCRYPTION_KEY=...
```

Generate `ATLASSIAN_TOKEN_ENCRYPTION_KEY` with:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

### Deploy and Connect a Pilot User

1. Restart the backend with the new env vars.
2. Open a Jira-write surface in MoveDocs.
3. Click `Connect Atlassian`.
4. Complete the Atlassian consent flow.
5. Verify `/api/auth/me` shows `jira_auth.connected = true`.
6. Post a comment from the ticket drawer and confirm Jira shows the real human author.

## 5. Fallback Behavior

If a user is not linked to Atlassian:

- comments and internal notes still post through `it-app`
- comment bodies are prefixed with a fallback actor line
- non-comment writes add an internal Jira audit note with the MoveDocs actor identity
- created issues append the fallback actor line to the description

This keeps the app usable during rollout while preserving operator traceability.
