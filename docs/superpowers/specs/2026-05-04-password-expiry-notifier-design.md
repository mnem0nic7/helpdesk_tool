# Password Expiry Email Notifier — Design Spec

**Date:** 2026-05-04
**Status:** Approved

---

## Overview

A leader-only background service that queries Active Directory daily, finds all enabled users whose passwords will expire within 14 days, and sends each one an HTML email directing them to reset their password at https://myaccount.microsoft.com/?ref=MeControl. Notifications continue daily until the user resets their password (i.e., until their `pwdLastSet` advances past the 14-day window). All activity is recorded to the database.

Starts in **test mode** (logs only, no email sent) until explicitly enabled via config.

---

## Architecture

- **New file:** `backend/password_expiry_notifier.py`
- Pattern mirrors `backend/deactivation_schedule.py` exactly: a class with an asyncio background task, polled every 60 seconds, executing the full job once per calendar day.
- Registered as a leader-only service in `backend/main.py`.
- No new API routes.

---

## Configuration (`backend/config.py`)

| Env var | Default | Description |
|---|---|---|
| `PASSWORD_EXPIRY_NOTIFY_ENABLED` | `false` | Set to `true` to send real emails. `false` = test mode (log only). |
| `AD_MAX_PWD_AGE_DAYS` | `90` | Domain max password age in days. |
| `PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE` | `14` | How many days before expiry to begin notifying. |

---

## Data Model

### Migration: `backend/storage_migrations/0024_password_expiry_notifications.sql`

**Table: `password_expiry_notifications`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT | UUID, primary key |
| `sam_account_name` | TEXT | |
| `email` | TEXT | `mail` attribute at time of send |
| `expiry_date` | TEXT | ISO date when password expires (`YYYY-MM-DD`) |
| `days_until_expiry` | INTEGER | Days remaining at time of notification |
| `notified_at` | TEXT | ISO datetime UTC |
| `test_mode` | SMALLINT | `1` = dry run, `0` = real send |

**Table: `password_expiry_notify_runs`**

| Column | Type | Notes |
|---|---|---|
| `run_date` | TEXT | `YYYY-MM-DD`, unique — used to gate one run per day |
| `ran_at` | TEXT | ISO datetime UTC |
| `users_notified` | INTEGER | Count of users notified (or would-be notified in test mode) |
| `test_mode` | SMALLINT | `1` = dry run, `0` = real send |

---

## Daily Job Logic

1. Poll loop checks every 60 seconds: has a `password_expiry_notify_runs` row for today's date already been inserted? If yes, skip until tomorrow.
2. Fetch all AD users via `ad_client.search_users()`, incrementing `page` until the returned `users` list is shorter than `limit` (page size 200).
3. Skip users where:
   - `enabled == False`
   - `mail` attribute is empty
   - `pwd_last_set` is null
4. For each remaining user:
   - Compute `expiry_date = pwd_last_set + AD_MAX_PWD_AGE_DAYS`
   - Compute `days_until_expiry = (expiry_date - today).days`
   - Skip if `days_until_expiry <= 0` or `days_until_expiry > PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE`
5. Dedup check: if a `password_expiry_notifications` row already exists for this `sam_account_name` with `notified_at` date = today, skip (guards against double-run edge cases).
6. **Test mode (`PASSWORD_EXPIRY_NOTIFY_ENABLED=false`):** log `[TEST MODE] Would notify {sam} <{email}> — expires in {N} days`. Write DB row with `test_mode=1`.
7. **Live mode (`PASSWORD_EXPIRY_NOTIFY_ENABLED=true`):** call `email_service.send_email(...)`. Write DB row with `test_mode=0` on success; log and skip DB write on failure.
8. After all users processed, insert row into `password_expiry_notify_runs`.

---

## Email Template

**Subject:** `Your password expires in {N} day(s) — action required`

**Body (HTML):**

```html
<p>Hi {display_name},</p>
<p>Your network password will expire in <strong>{N} day(s)</strong> (on {expiry_date}).</p>
<p>Please reset it before it expires to avoid losing access:</p>
<p><a href="https://myaccount.microsoft.com/?ref=MeControl">Reset your password</a></p>
<p>If you need help, contact the IT Help Desk.</p>
<p>— IT Team</p>
```

**Sender:** `it-ai@librasolutionsgroup.com` (existing shared mailbox from `email_service.py`).

---

## Integration Points

- `backend/config.py` — add three new env vars
- `backend/password_expiry_notifier.py` — new module (class + background runner)
- `backend/storage_migrations/0024_password_expiry_notifications.sql` — new migration
- `backend/main.py` — wire up as leader-only service in `_start_leader_services` / `_stop_leader_services`

---

## Out of Scope

- Frontend UI for viewing notification history (logs and DB rows are sufficient for now)
- Per-user opt-out
- Fine-grained password policies (PSOs / per-OU max age) — flat 90-day domain default only
