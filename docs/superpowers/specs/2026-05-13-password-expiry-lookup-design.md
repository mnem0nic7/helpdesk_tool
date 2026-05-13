# Password Expiry Lookup — Design Spec

**Date:** 2026-05-13
**Status:** Approved

## Summary

Add a password expiry lookup tool to the Tools page. Given a user identifier (email, UPN, or sAMAccountName), it returns password expiry information from both on-prem Active Directory and Entra (Azure AD). Available to all signed-in users on both the primary and azure site scopes.

---

## Architecture

No new files are created. Changes are additions to four existing modules:

| Module | Change |
|---|---|
| `backend/ad_client.py` | Add `get_password_expiry(identifier)` |
| `backend/azure_client.py` | Add `get_entra_password_expiry(identifier)` |
| `backend/routes_tools.py` | Add `GET /api/tools/password-expiry` |
| `frontend/src/pages/ToolsPage.tsx` | Add new section card |
| `frontend/src/lib/api.ts` | Add `PasswordExpiryResult` type + fetch helper |

---

## Backend

### `GET /api/tools/password-expiry?user=<identifier>`

- Protected by the standard tools session guard (`_require_tools_session`) — available to all signed-in users.
- Calls `ad_client.get_password_expiry()` and `azure_client.get_entra_password_expiry()` in parallel using `asyncio.run_in_executor` (both are synchronous blocking calls).
- Returns a combined `PasswordExpiryResponse`. If either source errors or is unconfigured, that source block carries `status: "unavailable"` or `"not_configured"` with an `error` string — the other block still renders normally.

### Response shape

```json
{
  "identifier": "jsmith@domain.com",
  "ad": {
    "status": "ok",
    "display_name": "John Smith",
    "sam_account_name": "jsmith",
    "upn": "jsmith@domain.com",
    "enabled": true,
    "pwd_last_set": "2025-11-01T14:32:00+00:00",
    "password_never_expires": false,
    "password_expires_at": "2026-05-01T14:32:00+00:00",
    "days_remaining": 12,
    "policy_source": "domain_default",
    "policy_name": "Default Domain Policy",
    "max_password_age_days": 180,
    "error": null
  },
  "entra": {
    "status": "ok",
    "display_name": "John Smith",
    "upn": "jsmith@domain.com",
    "enabled": true,
    "last_password_change": "2025-11-01T14:32:00+00:00",
    "password_never_expires": false,
    "password_expires_at": "2026-05-01T14:32:00+00:00",
    "days_remaining": 12,
    "policy_name": "Default password policy",
    "max_password_age_days": 180,
    "error": null
  }
}
```

`status` values per source block: `"ok"` | `"unavailable"` | `"not_found"` | `"not_configured"`

### `ad_client.get_password_expiry(identifier: str) -> dict`

1. Resolve the user: try `find_user_by_upn_or_email(identifier)` first; fall back to `get_user(identifier)` treating it as a SAM. If neither finds a user, return `status: "not_found"`.
2. Read `pwdLastSet` and `userAccountControl` from the resolved user entry (already in `_USER_ATTRS`).
3. Check `msDS-ResultantPSO` on the user entry (add to `_USER_ATTRS`). If present, fetch that PSO object and read `msDS-MaximumPasswordAge` for the fine-grained max age.
4. If no PSO, query the domain root (`""` base, `BASE` scope) for `maxPwdAge`.
5. Convert the 100-nanosecond negative interval to days.
6. Compute `password_expires_at = pwd_last_set + max_password_age_days`.
7. Special cases:
   - `password_never_expires` UAC flag set → `password_expires_at = null`, `days_remaining = null`.
   - `pwdLastSet = 0` → password must change at next logon; treat as expired (`days_remaining = 0`, `password_expires_at = null`, include `must_change_at_next_logon: true`).
8. Return `policy_source: "domain_default"` or `"fine_grained"` with the policy name.

### `azure_client.get_entra_password_expiry(identifier: str) -> dict`

1. Resolve the user via Graph `GET /users/{identifier}?$select=id,displayName,userPrincipalName,accountEnabled,lastPasswordChangeDateTime,passwordPolicies`.
2. `passwordPolicies` containing `"DisablePasswordExpiration"` → `password_never_expires = true`.
3. Fetch tenant password validity from `GET /domains` — find the verified default domain and read `passwordValidityPeriodInDays` (Graph default: 90 days if not set).
4. Compute `password_expires_at = last_password_change + max_password_age_days`.
5. Return structured dict with same field contract as the AD block.

---

## Frontend

### New section card on ToolsPage

Placed after the "List Inbox rules" card. Available to all users on both primary and azure scopes (no admin gate).

**Interaction model:** Submit-on-button-press (same pattern as mailbox rules). Input stays populated after lookup. React Query key is the submitted identifier, not the live input value, so typing doesn't trigger refetches.

**Result card layout:**

- Header: display name + UPN/email resolved from either source.
- Two labelled sub-sections: "On-prem AD" and "Entra (Azure AD)".
- Each sub-section uses `CountCard` chips for:
  - Days remaining (color-coded: red ≤ 14 days, amber ≤ 30 days, green > 30 days)
  - Last password set date
  - Account enabled/disabled status
- Below the chips: expiry date, policy name, max age, and policy source (AD only).
- "Never expires" replaces the expiry chip when `password_never_expires = true`.
- "Must change at next logon" warning badge when `must_change_at_next_logon = true`.
- If a source returns `status: "unavailable"` or `"not_configured"`, that half renders a muted banner ("AD not configured" / "Entra unavailable") — the other half still displays normally.
- If `status: "not_found"`, that half shows "Not found in [AD / Entra]".

### Types (`frontend/src/lib/api.ts`)

```typescript
export type PasswordExpirySourceStatus = "ok" | "unavailable" | "not_found" | "not_configured";

export interface PasswordExpiryAdResult {
  status: PasswordExpirySourceStatus;
  display_name: string;
  sam_account_name: string;
  upn: string;
  enabled: boolean;
  pwd_last_set: string | null;
  must_change_at_next_logon: boolean;
  password_never_expires: boolean;
  password_expires_at: string | null;
  days_remaining: number | null;
  policy_source: "domain_default" | "fine_grained";
  policy_name: string;
  max_password_age_days: number | null;
  error: string | null;
}

export interface PasswordExpiryEntraResult {
  status: PasswordExpirySourceStatus;
  display_name: string;
  upn: string;
  enabled: boolean;
  last_password_change: string | null;
  password_never_expires: boolean;
  password_expires_at: string | null;
  days_remaining: number | null;
  policy_name: string;
  max_password_age_days: number | null;
  error: string | null;
}

export interface PasswordExpiryResult {
  identifier: string;
  ad: PasswordExpiryAdResult;
  entra: PasswordExpiryEntraResult;
}
```

---

## Error handling

| Scenario | Behaviour |
|---|---|
| AD not configured | `ad.status = "not_configured"`, Entra block still renders |
| Entra Graph unavailable | `entra.status = "unavailable"` with error string, AD block still renders |
| User not found in one source | That block shows `status = "not_found"` |
| User not found in either source | Both blocks show not_found; card header shows the searched identifier |
| Domain root query fails | Treat as unavailable, surface error in `ad.error` |
| `pwdLastSet = 0` | `must_change_at_next_logon = true`, `days_remaining = 0` |
| `password_never_expires = true` | `password_expires_at = null`, `days_remaining = null`, chip shows "Never expires" |

---

## Out of scope

- Write operations (no password reset from this tool — that already exists in the offboarding/deactivation flows).
- Fine-grained Entra Conditional Access password policies (only the default domain password policy is read).
- Caching results (point-in-time lookup, no background refresh needed).
