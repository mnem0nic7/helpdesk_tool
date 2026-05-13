# Password Expiry Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Tools page lookup that shows when a user's password will expire, drawing from both on-prem Active Directory and Entra (Azure AD).

**Architecture:** A single `GET /api/tools/password-expiry?user=<identifier>` route calls `ad_client.get_password_expiry` and `AzureClient().get_entra_password_expiry` in parallel (via `ThreadPoolExecutor`), returning a combined payload. Each source block carries its own `status` field so one unavailable source doesn't break the other. The frontend section on ToolsPage submits on button press and renders a two-panel result card using the existing `CountCard` + `section` patterns.

**Tech Stack:** Python (FastAPI, ldap3, pydantic), React 19, React Query 5, Tailwind CSS 4, TypeScript

---

## File Map

| File | Change |
|---|---|
| `backend/ad_client.py` | Add `timedelta` import; add `msDS-ResultantPSO` to `_USER_ATTRS`; add `pso_dn` + `must_change_at_next_logon` to `_entry_to_user`; add `_get_domain_max_password_age_days()`, `_get_pso_max_password_age_days()`, `get_password_expiry()` |
| `backend/azure_client.py` | Add `get_entra_password_expiry()` method to `AzureClient` class |
| `backend/models.py` | Add `PasswordExpiryLookupAdResult`, `PasswordExpiryLookupEntraResult`, `PasswordExpiryLookupResponse` |
| `backend/routes_tools.py` | Add `concurrent.futures` import; import `AzureClient`; import new models; add `GET /api/tools/password-expiry` |
| `backend/tests/test_routes_tools.py` | Add tests for the new route |
| `frontend/src/lib/api.ts` | Add `PasswordExpiryLookupAdResult`, `PasswordExpiryLookupEntraResult`, `PasswordExpiryLookupResult` interfaces; add `lookupPasswordExpiry` method |
| `frontend/src/pages/ToolsPage.tsx` | Add `PasswordExpiryLookupPanel` component; add state + query + section card |

---

## Task 1: Extend `ad_client.py` — user entry + domain policy helpers

**Files:**
- Modify: `backend/ad_client.py`

- [ ] **Step 1: Add `timedelta` to the datetime import**

In `backend/ad_client.py`, line 15, change:
```python
from datetime import datetime, timezone
```
to:
```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 2: Add `msDS-ResultantPSO` to `_USER_ATTRS`**

In `backend/ad_client.py`, find `_USER_ATTRS` (line 48). Add `"msDS-ResultantPSO"` to the list:
```python
_USER_ATTRS = [
    "sAMAccountName", "userPrincipalName", "displayName", "givenName", "sn",
    "mail", "telephoneNumber", "mobile", "department", "title", "manager",
    "description", "streetAddress", "l", "st", "postalCode", "co",
    "userAccountControl", "accountExpires", "pwdLastSet", "lastLogonTimestamp",
    "lockoutTime", "badPwdCount", "distinguishedName", "objectGUID",
    "whenCreated", "whenChanged", "memberOf", "employeeID", "company",
    "msDS-ResultantPSO",
]
```

- [ ] **Step 3: Add `pso_dn` and `must_change_at_next_logon` to `_entry_to_user`**

In `backend/ad_client.py`, inside `_entry_to_user`, add two new fields after the `"member_of"` line (currently the last field before the closing `}`):

```python
        "member_of": [str(g) for g in (attrs.get("memberOf") or [])],
        "pso_dn": str(_first(attrs.get("msDS-ResultantPSO")) or "") or None,
        "must_change_at_next_logon": _pwd_must_change(attrs.get("pwdLastSet")),
    }
```

Add the helper just above `_entry_to_user` (around line 191):

```python
def _pwd_must_change(raw_pwd_last_set: Any) -> bool:
    val = _first(raw_pwd_last_set)
    if val is None:
        return False
    try:
        return int(val) == 0
    except (TypeError, ValueError):
        return False
```

- [ ] **Step 4: Add domain max password age helper**

After `_entry_to_user` in `backend/ad_client.py`, add:

```python
def _get_domain_max_password_age_days() -> int | None:
    """Query the domain root for maxPwdAge and return as days, or None on error."""
    try:
        conn = _get_connection()
    except (ADError, ADNotConfigured):
        return None
    try:
        conn.search("", "(objectClass=*)", BASE, attributes=["maxPwdAge"])
        if not conn.entries:
            return None
        raw = _first(conn.entries[0].entry_attributes_as_dict.get("maxPwdAge"))
        if raw is None:
            return None
        val = abs(int(raw))
        if val == 0:
            return None
        return val // (10_000_000 * 86400)
    except (LDAPException, TypeError, ValueError):
        return None
    finally:
        conn.unbind()
```

- [ ] **Step 5: Add PSO max password age helper**

Directly after `_get_domain_max_password_age_days`, add:

```python
def _get_pso_max_password_age_days(pso_dn: str) -> tuple[int | None, str]:
    """Fetch a PSO object and return (max_age_days, policy_name). Falls back to (None, pso_dn)."""
    try:
        conn = _get_connection()
    except (ADError, ADNotConfigured):
        return None, pso_dn
    try:
        conn.search(pso_dn, "(objectClass=*)", BASE, attributes=["msDS-MaximumPasswordAge", "name", "cn"])
        if not conn.entries:
            return None, pso_dn
        attrs = conn.entries[0].entry_attributes_as_dict
        name = str(_first(attrs.get("name") or attrs.get("cn")) or pso_dn)
        raw = _first(attrs.get("msDS-MaximumPasswordAge"))
        if raw is None:
            return None, name
        val = abs(int(raw))
        if val == 0:
            return None, name
        return val // (10_000_000 * 86400), name
    except (LDAPException, TypeError, ValueError):
        return None, pso_dn
    finally:
        conn.unbind()
```

- [ ] **Step 6: Write failing tests**

In `backend/tests/` create a new file `test_ad_client_password_expiry.py`:

```python
from unittest.mock import MagicMock, patch
import pytest


def _mock_user(pwd_last_set_raw="133800000000000000", pso_dn=None, password_never_expires=False, enabled=True):
    """Build a minimal _entry_to_user-style dict."""
    uac = 512 | (0x10000 if password_never_expires else 0) | (0 if enabled else 0x2)
    entry = MagicMock()
    attrs = {
        "sAMAccountName": ["jsmith"],
        "userPrincipalName": ["jsmith@example.com"],
        "displayName": ["John Smith"],
        "givenName": ["John"],
        "sn": ["Smith"],
        "mail": ["jsmith@example.com"],
        "userAccountControl": [str(uac)],
        "pwdLastSet": [pwd_last_set_raw],
        "msDS-ResultantPSO": [pso_dn] if pso_dn else [],
        "accountExpires": [],
        "lastLogonTimestamp": [],
        "lockoutTime": [],
        "badPwdCount": ["0"],
        "memberOf": [],
        # other attrs empty
        "telephoneNumber": [], "mobile": [], "department": [], "title": [],
        "manager": [], "description": [], "streetAddress": [], "l": [], "st": [],
        "postalCode": [], "co": [], "company": [], "employeeID": [],
        "distinguishedName": ["CN=jsmith,DC=example,DC=com"],
        "objectGUID": [], "whenCreated": [], "whenChanged": [],
    }
    entry.entry_attributes_as_dict = attrs
    entry.entry_dn = "CN=jsmith,DC=example,DC=com"
    return entry


def test_get_password_expiry_returns_ok(monkeypatch):
    import ad_client

    monkeypatch.setattr(ad_client, "ad_configured", lambda: True)

    mock_conn = MagicMock()
    mock_conn.entries = [_mock_user()]
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)

    domain_conn = MagicMock()
    # maxPwdAge = -15552000000000000 (180 days in 100ns intervals, negative)
    domain_conn.entries = [MagicMock(entry_attributes_as_dict={"maxPwdAge": ["-15552000000000000"]})]

    connections = iter([mock_conn, domain_conn])
    monkeypatch.setattr(ad_client, "_get_connection", lambda: next(connections))

    result = ad_client.get_password_expiry("jsmith@example.com")

    assert result["status"] == "ok"
    assert result["sam_account_name"] == "jsmith"
    assert result["policy_source"] == "domain_default"
    assert result["max_password_age_days"] == 180
    assert result["must_change_at_next_logon"] is False
    assert result["password_never_expires"] is False
    assert result["password_expires_at"] is not None
    assert result["days_remaining"] is not None


def test_get_password_expiry_not_configured(monkeypatch):
    import ad_client

    monkeypatch.setattr(ad_client, "ad_configured", lambda: False)

    result = ad_client.get_password_expiry("jsmith@example.com")

    assert result["status"] == "not_configured"
    assert result["error"] is not None


def test_get_password_expiry_not_found(monkeypatch):
    import ad_client

    monkeypatch.setattr(ad_client, "ad_configured", lambda: True)

    monkeypatch.setattr(ad_client, "find_user_by_upn_or_email", lambda _: None)

    mock_conn = MagicMock()
    mock_conn.entries = []
    monkeypatch.setattr(ad_client, "_get_connection", lambda: mock_conn)

    result = ad_client.get_password_expiry("nobody@example.com")

    assert result["status"] == "not_found"


def test_get_password_expiry_must_change_at_next_logon(monkeypatch):
    import ad_client

    monkeypatch.setattr(ad_client, "ad_configured", lambda: True)

    mock_conn = MagicMock()
    mock_conn.entries = [_mock_user(pwd_last_set_raw="0")]  # pwdLastSet=0 means must change
    domain_conn = MagicMock()
    domain_conn.entries = [MagicMock(entry_attributes_as_dict={"maxPwdAge": ["-15552000000000000"]})]
    connections = iter([mock_conn, domain_conn])
    monkeypatch.setattr(ad_client, "_get_connection", lambda: next(connections))

    result = ad_client.get_password_expiry("jsmith@example.com")

    assert result["must_change_at_next_logon"] is True
    assert result["days_remaining"] == 0


def test_get_password_expiry_never_expires(monkeypatch):
    import ad_client

    monkeypatch.setattr(ad_client, "ad_configured", lambda: True)

    mock_conn = MagicMock()
    mock_conn.entries = [_mock_user(password_never_expires=True)]
    domain_conn = MagicMock()
    domain_conn.entries = [MagicMock(entry_attributes_as_dict={"maxPwdAge": ["-15552000000000000"]})]
    connections = iter([mock_conn, domain_conn])
    monkeypatch.setattr(ad_client, "_get_connection", lambda: next(connections))

    result = ad_client.get_password_expiry("jsmith@example.com")

    assert result["password_never_expires"] is True
    assert result["password_expires_at"] is None
    assert result["days_remaining"] is None
```

- [ ] **Step 7: Run tests to verify they fail**

```bash
cd /workspace/atlassian && .venv/bin/pytest backend/tests/test_ad_client_password_expiry.py -v
```

Expected: ImportError or AttributeError — `get_password_expiry` does not exist yet.

- [ ] **Step 8: Implement `get_password_expiry`**

Add at the end of `backend/ad_client.py` (before any existing trailing helpers):

```python
def get_password_expiry(identifier: str) -> dict[str, Any]:
    """Return password expiry info for a user identified by UPN, email, or SAM."""
    if not ad_configured():
        return {"status": "not_configured", "error": "Active Directory is not configured"}

    user = find_user_by_upn_or_email(identifier)
    if user is None:
        try:
            user = get_user(identifier)
        except ADError:
            pass

    if user is None:
        return {"status": "not_found", "error": f"User '{identifier}' not found in Active Directory"}

    pso_dn: str | None = user.get("pso_dn")
    policy_source = "domain_default"
    policy_name = "Default Domain Policy"
    max_age_days: int | None

    if pso_dn:
        max_age_days, policy_name = _get_pso_max_password_age_days(pso_dn)
        policy_source = "fine_grained"
    else:
        max_age_days = _get_domain_max_password_age_days()

    pwd_last_set: str | None = user.get("pwd_last_set")
    must_change: bool = user.get("must_change_at_next_logon", False)
    password_never_expires: bool = user["flags"]["password_never_expires"]

    password_expires_at: str | None = None
    days_remaining: int | None = None

    if must_change:
        days_remaining = 0
    elif not password_never_expires and pwd_last_set and max_age_days:
        last_set_dt = datetime.fromisoformat(pwd_last_set)
        expires_dt = last_set_dt + timedelta(days=max_age_days)
        password_expires_at = expires_dt.isoformat()
        now = datetime.now(tz=timezone.utc)
        days_remaining = max(0, (expires_dt - now).days)

    return {
        "status": "ok",
        "display_name": user.get("display_name", ""),
        "sam_account_name": user.get("sam_account_name", ""),
        "upn": user.get("upn", ""),
        "enabled": user["flags"]["enabled"],
        "pwd_last_set": pwd_last_set,
        "must_change_at_next_logon": must_change,
        "password_never_expires": password_never_expires,
        "password_expires_at": password_expires_at,
        "days_remaining": days_remaining,
        "policy_source": policy_source,
        "policy_name": policy_name,
        "max_password_age_days": max_age_days,
        "error": None,
    }
```

- [ ] **Step 9: Run tests to verify they pass**

```bash
cd /workspace/atlassian && .venv/bin/pytest backend/tests/test_ad_client_password_expiry.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/ad_client.py backend/tests/test_ad_client_password_expiry.py
git commit -m "feat: add get_password_expiry to ad_client with domain/PSO policy support"
```

---

## Task 2: Add `get_entra_password_expiry` to `azure_client.py`

**Files:**
- Modify: `backend/azure_client.py`
- Create: `backend/tests/test_azure_client_password_expiry.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_azure_client_password_expiry.py`:

```python
from unittest.mock import MagicMock, patch
import pytest


def _make_client(configured=True):
    from azure_client import AzureClient
    client = AzureClient()
    if not configured:
        client.__class__.configured = property(lambda self: False)
    return client


def test_get_entra_password_expiry_not_configured():
    from azure_client import AzureClient
    client = AzureClient()
    # Patch configured property to False
    with patch.object(type(client), "configured", new_callable=lambda: property(lambda self: False)):
        result = client.get_entra_password_expiry("jsmith@example.com")
    assert result["status"] == "not_configured"
    assert result["error"] is not None


def test_get_entra_password_expiry_ok(monkeypatch):
    from azure_client import AzureClient
    client = AzureClient()

    monkeypatch.setattr(type(client), "configured", property(lambda self: True))

    user_payload = {
        "id": "abc123",
        "displayName": "John Smith",
        "userPrincipalName": "jsmith@example.com",
        "accountEnabled": True,
        "lastPasswordChangeDateTime": "2025-11-01T14:32:00Z",
        "passwordPolicies": None,
    }
    domain_payload = [
        {"id": "example.com", "isDefault": True, "passwordValidityPeriodInDays": 180}
    ]

    monkeypatch.setattr(client, "graph_request", lambda method, path, **kw: user_payload)
    monkeypatch.setattr(client, "graph_paged_get", lambda path, **kw: domain_payload)

    result = client.get_entra_password_expiry("jsmith@example.com")

    assert result["status"] == "ok"
    assert result["display_name"] == "John Smith"
    assert result["max_password_age_days"] == 180
    assert result["password_never_expires"] is False
    assert result["password_expires_at"] is not None
    assert result["days_remaining"] is not None


def test_get_entra_password_expiry_never_expires(monkeypatch):
    from azure_client import AzureClient
    client = AzureClient()

    monkeypatch.setattr(type(client), "configured", property(lambda self: True))

    user_payload = {
        "id": "abc123",
        "displayName": "John Smith",
        "userPrincipalName": "jsmith@example.com",
        "accountEnabled": True,
        "lastPasswordChangeDateTime": "2025-11-01T14:32:00Z",
        "passwordPolicies": "DisablePasswordExpiration",
    }
    domain_payload = [{"id": "example.com", "isDefault": True, "passwordValidityPeriodInDays": 180}]

    monkeypatch.setattr(client, "graph_request", lambda method, path, **kw: user_payload)
    monkeypatch.setattr(client, "graph_paged_get", lambda path, **kw: domain_payload)

    result = client.get_entra_password_expiry("jsmith@example.com")

    assert result["password_never_expires"] is True
    assert result["password_expires_at"] is None
    assert result["days_remaining"] is None


def test_get_entra_password_expiry_not_found(monkeypatch):
    from azure_client import AzureClient, AzureApiError
    client = AzureClient()

    monkeypatch.setattr(type(client), "configured", property(lambda self: True))
    monkeypatch.setattr(client, "graph_request", MagicMock(side_effect=AzureApiError("Request_ResourceNotFound")))

    result = client.get_entra_password_expiry("nobody@example.com")

    assert result["status"] == "not_found"


def test_get_entra_password_expiry_tenant_never_expires(monkeypatch):
    from azure_client import AzureClient
    client = AzureClient()

    monkeypatch.setattr(type(client), "configured", property(lambda self: True))

    user_payload = {
        "id": "abc123",
        "displayName": "John Smith",
        "userPrincipalName": "jsmith@example.com",
        "accountEnabled": True,
        "lastPasswordChangeDateTime": "2025-11-01T14:32:00Z",
        "passwordPolicies": None,
    }
    # passwordValidityPeriodInDays == 2147483647 means tenant-wide never expires
    domain_payload = [{"id": "example.com", "isDefault": True, "passwordValidityPeriodInDays": 2147483647}]

    monkeypatch.setattr(client, "graph_request", lambda method, path, **kw: user_payload)
    monkeypatch.setattr(client, "graph_paged_get", lambda path, **kw: domain_payload)

    result = client.get_entra_password_expiry("jsmith@example.com")

    assert result["password_never_expires"] is True
    assert result["password_expires_at"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/atlassian && .venv/bin/pytest backend/tests/test_azure_client_password_expiry.py -v
```

Expected: AttributeError — `get_entra_password_expiry` does not exist yet.

- [ ] **Step 3: Implement `get_entra_password_expiry` on `AzureClient`**

In `backend/azure_client.py`, find `get_user` (around line 1169) and add the new method immediately after `get_user`:

```python
    def get_entra_password_expiry(self, identifier: str) -> dict[str, Any]:
        """Return password expiry info for an Entra user by UPN, email, or object ID."""
        if not self.configured:
            return {"status": "not_configured", "error": "Entra is not configured: missing app credentials"}

        _select = "id,displayName,userPrincipalName,accountEnabled,lastPasswordChangeDateTime,passwordPolicies"
        try:
            user = self.graph_request("GET", f"users/{identifier}", params={"$select": _select})
        except AzureApiError as exc:
            err = str(exc)
            err_lower = err.lower()
            if any(k in err_lower for k in ("resourcenotfound", "does not exist", "not found", "badrequest")):
                return {"status": "not_found", "error": f"User '{identifier}' not found in Entra"}
            return {"status": "unavailable", "error": err}

        password_never_expires = "DisablePasswordExpiration" in (user.get("passwordPolicies") or "")
        last_change: str | None = user.get("lastPasswordChangeDateTime")

        max_age_days = 90
        policy_name = "Default password policy (90 days)"
        try:
            domains = self.graph_paged_get("domains", params={"$select": "id,isDefault,passwordValidityPeriodInDays"})
            default_domain = next((d for d in domains if d.get("isDefault")), None)
            if default_domain:
                validity = default_domain.get("passwordValidityPeriodInDays")
                if validity is not None:
                    if int(validity) == 2147483647:
                        password_never_expires = True
                    else:
                        max_age_days = int(validity)
                        policy_name = f"Domain policy ({max_age_days} days)"
        except (AzureApiError, StopIteration, TypeError, ValueError):
            pass

        password_expires_at: str | None = None
        days_remaining: int | None = None

        if not password_never_expires and last_change and max_age_days:
            last_dt = datetime.fromisoformat(last_change.replace("Z", "+00:00"))
            expires_dt = last_dt + timedelta(days=max_age_days)
            password_expires_at = expires_dt.isoformat()
            now = datetime.now(tz=timezone.utc)
            days_remaining = max(0, (expires_dt - now).days)

        return {
            "status": "ok",
            "display_name": user.get("displayName", ""),
            "upn": user.get("userPrincipalName", ""),
            "enabled": bool(user.get("accountEnabled")),
            "last_password_change": last_change,
            "password_never_expires": password_never_expires,
            "password_expires_at": password_expires_at,
            "days_remaining": days_remaining,
            "policy_name": policy_name,
            "max_password_age_days": max_age_days if not password_never_expires else None,
            "error": None,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /workspace/atlassian && .venv/bin/pytest backend/tests/test_azure_client_password_expiry.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/azure_client.py backend/tests/test_azure_client_password_expiry.py
git commit -m "feat: add get_entra_password_expiry to AzureClient"
```

---

## Task 3: Add Pydantic response models to `models.py`

**Files:**
- Modify: `backend/models.py`

- [ ] **Step 1: Add models**

In `backend/models.py`, find the `MailboxRulesResponse` class (around line 794) and add the three new models immediately before it:

```python
class PasswordExpiryLookupAdResult(BaseModel):
    status: str
    display_name: str = ""
    sam_account_name: str = ""
    upn: str = ""
    enabled: bool | None = None
    pwd_last_set: str | None = None
    must_change_at_next_logon: bool = False
    password_never_expires: bool = False
    password_expires_at: str | None = None
    days_remaining: int | None = None
    policy_source: str = ""
    policy_name: str = ""
    max_password_age_days: int | None = None
    error: str | None = None


class PasswordExpiryLookupEntraResult(BaseModel):
    status: str
    display_name: str = ""
    upn: str = ""
    enabled: bool | None = None
    last_password_change: str | None = None
    password_never_expires: bool = False
    password_expires_at: str | None = None
    days_remaining: int | None = None
    policy_name: str = ""
    max_password_age_days: int | None = None
    error: str | None = None


class PasswordExpiryLookupResponse(BaseModel):
    identifier: str
    ad: PasswordExpiryLookupAdResult
    entra: PasswordExpiryLookupEntraResult
```

- [ ] **Step 2: Verify models import cleanly**

```bash
cd /workspace/atlassian/backend && python -c "from models import PasswordExpiryLookupAdResult, PasswordExpiryLookupEntraResult, PasswordExpiryLookupResponse; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "feat: add PasswordExpiryLookup response models"
```

---

## Task 4: Add `GET /api/tools/password-expiry` route

**Files:**
- Modify: `backend/routes_tools.py`
- Modify: `backend/tests/test_routes_tools.py`

- [ ] **Step 1: Write failing tests**

Open `backend/tests/test_routes_tools.py` and add at the end:

```python
def test_password_expiry_returns_combined_result(test_client, monkeypatch):
    import routes_tools

    ad_result = {
        "status": "ok",
        "display_name": "John Smith",
        "sam_account_name": "jsmith",
        "upn": "jsmith@example.com",
        "enabled": True,
        "pwd_last_set": "2025-11-01T14:32:00+00:00",
        "must_change_at_next_logon": False,
        "password_never_expires": False,
        "password_expires_at": "2026-05-01T14:32:00+00:00",
        "days_remaining": 12,
        "policy_source": "domain_default",
        "policy_name": "Default Domain Policy",
        "max_password_age_days": 180,
        "error": None,
    }
    entra_result = {
        "status": "ok",
        "display_name": "John Smith",
        "upn": "jsmith@example.com",
        "enabled": True,
        "last_password_change": "2025-11-01T14:32:00+00:00",
        "password_never_expires": False,
        "password_expires_at": "2026-05-01T14:32:00+00:00",
        "days_remaining": 12,
        "policy_name": "Domain policy (180 days)",
        "max_password_age_days": 180,
        "error": None,
    }

    mock_ad = MagicMock()
    mock_ad.get_password_expiry.return_value = ad_result

    mock_azure_client_instance = MagicMock()
    mock_azure_client_instance.get_entra_password_expiry.return_value = entra_result
    MockAzureClient = MagicMock(return_value=mock_azure_client_instance)

    monkeypatch.setattr(routes_tools, "ad", mock_ad)
    monkeypatch.setattr(routes_tools, "AzureClient", MockAzureClient)

    resp = test_client.get(
        "/api/tools/password-expiry?user=jsmith@example.com",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["identifier"] == "jsmith@example.com"
    assert payload["ad"]["status"] == "ok"
    assert payload["ad"]["sam_account_name"] == "jsmith"
    assert payload["entra"]["status"] == "ok"
    assert payload["entra"]["display_name"] == "John Smith"
    mock_ad.get_password_expiry.assert_called_once_with("jsmith@example.com")
    mock_azure_client_instance.get_entra_password_expiry.assert_called_once_with("jsmith@example.com")


def test_password_expiry_missing_user_param_returns_422(test_client):
    resp = test_client.get(
        "/api/tools/password-expiry",
        headers={"host": "it-app.movedocs.com"},
    )
    assert resp.status_code == 422


def test_password_expiry_partial_result_when_ad_not_configured(test_client, monkeypatch):
    import routes_tools

    ad_result = {"status": "not_configured", "error": "Active Directory is not configured"}
    entra_result = {
        "status": "ok", "display_name": "John Smith", "upn": "jsmith@example.com",
        "enabled": True, "last_password_change": "2025-11-01T14:32:00+00:00",
        "password_never_expires": False, "password_expires_at": "2026-05-01T14:32:00+00:00",
        "days_remaining": 12, "policy_name": "Domain policy (180 days)",
        "max_password_age_days": 180, "error": None,
    }

    mock_ad = MagicMock()
    mock_ad.get_password_expiry.return_value = ad_result
    mock_azure_client_instance = MagicMock()
    mock_azure_client_instance.get_entra_password_expiry.return_value = entra_result
    MockAzureClient = MagicMock(return_value=mock_azure_client_instance)

    monkeypatch.setattr(routes_tools, "ad", mock_ad)
    monkeypatch.setattr(routes_tools, "AzureClient", MockAzureClient)

    resp = test_client.get(
        "/api/tools/password-expiry?user=jsmith@example.com",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ad"]["status"] == "not_configured"
    assert payload["entra"]["status"] == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/atlassian && .venv/bin/pytest backend/tests/test_routes_tools.py::test_password_expiry_returns_combined_result backend/tests/test_routes_tools.py::test_password_expiry_missing_user_param_returns_422 backend/tests/test_routes_tools.py::test_password_expiry_partial_result_when_ad_not_configured -v
```

Expected: FAIL — route does not exist yet.

- [ ] **Step 3: Add imports to `routes_tools.py`**

In `backend/routes_tools.py`, add to the existing imports:

```python
from concurrent.futures import ThreadPoolExecutor
from azure_client import AzureClient
```

Also add the new models to the `from models import (...)` block:
```python
from models import (
    ...
    PasswordExpiryLookupAdResult,
    PasswordExpiryLookupEntraResult,
    PasswordExpiryLookupResponse,
    ...
)
```

- [ ] **Step 4: Add the route**

Add the new route in `backend/routes_tools.py` after the `list_mailbox_rules` route (around line 260):

```python
@router.get("/password-expiry", response_model=PasswordExpiryLookupResponse)
def get_password_expiry(
    user: str = Query(..., min_length=1),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> PasswordExpiryLookupResponse:
    identifier = user.strip()

    def _fetch_ad() -> dict[str, Any]:
        try:
            return ad.get_password_expiry(identifier)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    def _fetch_entra() -> dict[str, Any]:
        try:
            return AzureClient().get_entra_password_expiry(identifier)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        ad_future = pool.submit(_fetch_ad)
        entra_future = pool.submit(_fetch_entra)
        ad_result = ad_future.result()
        entra_result = entra_future.result()

    return PasswordExpiryLookupResponse(
        identifier=identifier,
        ad=PasswordExpiryLookupAdResult(**ad_result),
        entra=PasswordExpiryLookupEntraResult(**entra_result),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /workspace/atlassian && .venv/bin/pytest backend/tests/test_routes_tools.py::test_password_expiry_returns_combined_result backend/tests/test_routes_tools.py::test_password_expiry_missing_user_param_returns_422 backend/tests/test_routes_tools.py::test_password_expiry_partial_result_when_ad_not_configured -v
```

Expected: All 3 tests PASS.

- [ ] **Step 6: Run full backend test suite to check for regressions**

```bash
cd /workspace/atlassian && .venv/bin/pytest backend/tests/ -q
```

Expected: All existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/routes_tools.py backend/tests/test_routes_tools.py
git commit -m "feat: add GET /api/tools/password-expiry route"
```

---

## Task 5: Add TypeScript types and API method

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add type interfaces**

In `frontend/src/lib/api.ts`, find the `PasswordExpiryStatus` interface (around line 5251). Add the new interfaces just before it:

```typescript
export type PasswordExpiryLookupSourceStatus = "ok" | "unavailable" | "not_found" | "not_configured";

export interface PasswordExpiryLookupAdResult {
  status: PasswordExpiryLookupSourceStatus;
  display_name: string;
  sam_account_name: string;
  upn: string;
  enabled: boolean | null;
  pwd_last_set: string | null;
  must_change_at_next_logon: boolean;
  password_never_expires: boolean;
  password_expires_at: string | null;
  days_remaining: number | null;
  policy_source: string;
  policy_name: string;
  max_password_age_days: number | null;
  error: string | null;
}

export interface PasswordExpiryLookupEntraResult {
  status: PasswordExpiryLookupSourceStatus;
  display_name: string;
  upn: string;
  enabled: boolean | null;
  last_password_change: string | null;
  password_never_expires: boolean;
  password_expires_at: string | null;
  days_remaining: number | null;
  policy_name: string;
  max_password_age_days: number | null;
  error: string | null;
}

export interface PasswordExpiryLookupResult {
  identifier: string;
  ad: PasswordExpiryLookupAdResult;
  entra: PasswordExpiryLookupEntraResult;
}
```

- [ ] **Step 2: Add API method**

In `frontend/src/lib/api.ts`, find `listMailboxRules` (around line 3926) and add the new method immediately after it:

```typescript
  lookupPasswordExpiry(user: string): Promise<PasswordExpiryLookupResult> {
    return fetchJSON<PasswordExpiryLookupResult>(`/api/tools/password-expiry${buildQuery({ user })}`);
  },
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /workspace/atlassian/frontend && npm run build 2>&1 | tail -20
```

Expected: Build succeeds with no TypeScript errors related to the new types.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add PasswordExpiryLookup types and lookupPasswordExpiry API method"
```

---

## Task 6: Add UI section to `ToolsPage.tsx`

**Files:**
- Modify: `frontend/src/pages/ToolsPage.tsx`

- [ ] **Step 1: Add the result panel component**

In `frontend/src/pages/ToolsPage.tsx`, find the `LoginAuditPanel` function (around line 300). Add the new component before it:

```typescript
function ExpiryChip({
  days,
  neverExpires,
  mustChange,
}: {
  days: number | null;
  neverExpires: boolean;
  mustChange: boolean;
}) {
  if (mustChange) {
    return <CountCard label="Days Remaining" value="Must change now" tone="text-red-700" />;
  }
  if (neverExpires) {
    return <CountCard label="Days Remaining" value="Never expires" tone="text-emerald-700" />;
  }
  if (days === null) {
    return <CountCard label="Days Remaining" value="—" />;
  }
  const tone = days <= 14 ? "text-red-700" : days <= 30 ? "text-amber-700" : "text-emerald-700";
  return <CountCard label="Days Remaining" value={String(days)} tone={tone} />;
}

function PasswordExpiryLookupPanel({ data }: { data: PasswordExpiryLookupResult }) {
  const resolvedName =
    data.ad.display_name || data.entra.display_name || data.identifier;
  const resolvedUpn = data.ad.upn || data.entra.upn || data.identifier;

  function formatDate(iso: string | null) {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  function SourceBlock({
    label,
    status,
    error,
    daysRemaining,
    neverExpires,
    mustChange,
    lastSet,
    expiresAt,
    enabled,
    policyName,
    policySource,
    maxAgeDays,
  }: {
    label: string;
    status: PasswordExpiryLookupSourceStatus;
    error: string | null;
    daysRemaining: number | null;
    neverExpires: boolean;
    mustChange: boolean;
    lastSet: string | null;
    expiresAt: string | null;
    enabled: boolean | null;
    policyName: string;
    policySource?: string;
    maxAgeDays: number | null;
  }) {
    if (status === "not_configured") {
      return (
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
          <p className="mt-2 text-sm text-slate-400">{label} is not configured on this server.</p>
        </div>
      );
    }
    if (status === "unavailable") {
      return (
        <div className="rounded-2xl border border-amber-100 bg-amber-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
          <p className="mt-2 text-sm text-amber-700">{error || `${label} is temporarily unavailable.`}</p>
        </div>
      );
    }
    if (status === "not_found") {
      return (
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
          <p className="mt-2 text-sm text-slate-400">User not found in {label}.</p>
        </div>
      );
    }
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
        <div className="mt-3 flex flex-wrap gap-3">
          <ExpiryChip days={daysRemaining} neverExpires={neverExpires} mustChange={mustChange} />
          <CountCard label="Last Set" value={formatDate(lastSet)} />
          <CountCard
            label="Account"
            value={enabled === null ? "—" : enabled ? "Enabled" : "Disabled"}
            tone={enabled === false ? "text-red-700" : "text-slate-900"}
          />
        </div>
        {mustChange && (
          <p className="mt-2 text-sm font-medium text-red-600">Password must be changed at next logon.</p>
        )}
        <dl className="mt-3 space-y-1 text-sm text-slate-600">
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-slate-400">Expires</dt>
            <dd>{neverExpires ? "Never" : formatDate(expiresAt)}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-slate-400">Policy</dt>
            <dd>{policyName || "—"}</dd>
          </div>
          {policySource && (
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-slate-400">Policy source</dt>
              <dd className="capitalize">{policySource.replace("_", " ")}</dd>
            </div>
          )}
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-slate-400">Max age</dt>
            <dd>{maxAgeDays !== null ? `${maxAgeDays} days` : "—"}</dd>
          </div>
        </dl>
      </div>
    );
  }

  return (
    <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Password Expiry</div>
        <h2 className="mt-1 text-2xl font-semibold text-slate-900">{resolvedName}</h2>
        <p className="mt-0.5 text-sm text-slate-500">{resolvedUpn}</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <SourceBlock
          label="On-prem AD"
          status={data.ad.status}
          error={data.ad.error}
          daysRemaining={data.ad.days_remaining}
          neverExpires={data.ad.password_never_expires}
          mustChange={data.ad.must_change_at_next_logon}
          lastSet={data.ad.pwd_last_set}
          expiresAt={data.ad.password_expires_at}
          enabled={data.ad.enabled}
          policyName={data.ad.policy_name}
          policySource={data.ad.policy_source}
          maxAgeDays={data.ad.max_password_age_days}
        />
        <SourceBlock
          label="Entra (Azure AD)"
          status={data.entra.status}
          error={data.entra.error}
          daysRemaining={data.entra.days_remaining}
          neverExpires={data.entra.password_never_expires}
          mustChange={false}
          lastSet={data.entra.last_password_change}
          expiresAt={data.entra.password_expires_at}
          enabled={data.entra.enabled}
          policyName={data.entra.policy_name}
          maxAgeDays={data.entra.max_password_age_days}
        />
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Add the import for the new types**

In `frontend/src/pages/ToolsPage.tsx`, find the import block at the top that imports from `"../lib/api.ts"` (around line 17). Add the new types:

```typescript
import {
  // ... existing imports ...
  PasswordExpiryLookupResult,
  PasswordExpiryLookupSourceStatus,
} from "../lib/api.ts";
```

- [ ] **Step 3: Add state and query**

In `ToolsPage` (the default export function, around line 1049), find the block of `useState` declarations and add:

```typescript
const [passwordExpiryInput, setPasswordExpiryInput] = useState("");
const [activePasswordExpiryLookup, setActivePasswordExpiryLookup] = useState<string | null>(null);
```

Find the block of `useQuery` calls and add:

```typescript
const passwordExpiryQuery = useQuery({
  queryKey: ["password-expiry", activePasswordExpiryLookup],
  queryFn: () => api.lookupPasswordExpiry(activePasswordExpiryLookup as string),
  enabled: hasSignedInUser && !!activePasswordExpiryLookup,
  retry: false,
});
```

- [ ] **Step 4: Add submit handler**

After the submit handlers for mailbox rules (around line 1560), add:

```typescript
function submitPasswordExpiryLookup() {
  const identifier = passwordExpiryInput.trim();
  if (!identifier) return;
  setActivePasswordExpiryLookup(identifier);
}
```

- [ ] **Step 5: Add the section card**

In the JSX, find the closing of the "List Inbox rules" section card (the last `</section>` in the right column, around line 2207). Directly after that closing tag, add the new section:

```tsx
<section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
  <div className="flex flex-wrap items-center justify-between gap-3">
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Password Expiry</div>
      <h2 className="mt-1 text-2xl font-semibold text-slate-900">Look up when a user&apos;s password expires</h2>
      <p className="mt-2 text-sm text-slate-600">
        Enter a user email, UPN, or sAMAccountName to check their on-prem AD and Entra (Azure AD) password expiry.
      </p>
    </div>
    <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">Read only</span>
  </div>

  <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-slate-700">Email, UPN, or sAMAccountName</label>
      <input
        type="text"
        value={passwordExpiryInput}
        onChange={(e) => setPasswordExpiryInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submitPasswordExpiryLookup();
        }}
        placeholder="jsmith@example.com or jsmith"
        className="rounded-xl border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-200"
      />
    </div>
    <button
      type="button"
      onClick={submitPasswordExpiryLookup}
      disabled={!passwordExpiryInput.trim() || passwordExpiryQuery.isFetching}
      className={buttonClass("primary", !passwordExpiryInput.trim() || passwordExpiryQuery.isFetching)}
    >
      {passwordExpiryQuery.isFetching ? "Looking up..." : "Look up"}
    </button>
  </div>

  {passwordExpiryQuery.isError && (
    <p className="text-sm text-red-600">
      {passwordExpiryQuery.error instanceof Error
        ? passwordExpiryQuery.error.message
        : "Lookup failed. Please try again."}
    </p>
  )}

  {passwordExpiryQuery.data && (
    <PasswordExpiryLookupPanel data={passwordExpiryQuery.data} />
  )}
</section>
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd /workspace/atlassian/frontend && npm run build 2>&1 | tail -30
```

Expected: Build succeeds with no errors.

- [ ] **Step 7: Run frontend tests**

```bash
cd /workspace/atlassian/frontend && npm run test:run 2>&1 | tail -20
```

Expected: All existing tests pass. (No new test file needed for the component — it's wired to the query which is covered by the route test.)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/ToolsPage.tsx frontend/src/lib/api.ts
git commit -m "feat: add password expiry lookup section to Tools page"
```

---

## Self-Review

**Spec coverage:**
- ✓ Accept email, UPN, or SAM → `find_user_by_upn_or_email` then SAM fallback in `get_password_expiry`
- ✓ AD source → Task 1
- ✓ Entra source → Task 2
- ✓ Parallel execution → `ThreadPoolExecutor` in Task 4
- ✓ Per-source status fields → all four status values handled
- ✓ Fine-grained PSO → `_get_pso_max_password_age_days` + `msDS-ResultantPSO` in attrs
- ✓ `must_change_at_next_logon` when `pwdLastSet=0` → Task 1 `_pwd_must_change`
- ✓ `password_never_expires` flag → read from UAC in AD, from `passwordPolicies` in Entra
- ✓ Tenant-wide never expires (`2147483647`) → handled in `get_entra_password_expiry`
- ✓ All signed-in users → `_require_tools_session` (not admin gate)
- ✓ Both scopes → `_ensure_tools_site` allows `primary` and `azure`
- ✓ "Full" display: expiry, days remaining, last set, enabled, policy source, policy name, max age days → `PasswordExpiryLookupPanel`
- ✓ Color-coded days chip → `ExpiryChip`
- ✓ Partial result when one source unavailable → each source block handles its own status independently

**Type consistency:**
- `PasswordExpiryLookupAdResult` matches between `models.py` and `api.ts`
- `must_change_at_next_logon` present in both the dict returned by `get_password_expiry` and the Pydantic model
- `lookupPasswordExpiry` returns `PasswordExpiryLookupResult` matching the route's `response_model=PasswordExpiryLookupResponse`
- `PasswordExpiryLookupSourceStatus` type used in both `SourceBlock` props and interface definition
