from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest


def _filetime_days_ago(days: int) -> str:
    """Windows FILETIME (100ns since 1601-01-01) for `days` before now."""
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return str(int((dt - epoch).total_seconds() * 10_000_000))


def _mock_user(pwd_last_set_raw=None, pso_dn=None, password_never_expires=False, enabled=True):
    """Build a minimal _entry_to_user-style dict."""
    if pwd_last_set_raw is None:
        # Computed relative to "now" so this fixture never rots into a
        # false failure as real time passes (see 2026-09-01 incident).
        pwd_last_set_raw = _filetime_days_ago(10)
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
    # maxPwdAge = -155520000000000 (180 days in 100ns intervals, negative)
    domain_conn.entries = [MagicMock(entry_attributes_as_dict={"maxPwdAge": ["-155520000000000"]})]

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
    assert result["days_remaining"] > 0


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
    domain_conn.entries = [MagicMock(entry_attributes_as_dict={"maxPwdAge": ["-155520000000000"]})]
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
    domain_conn.entries = [MagicMock(entry_attributes_as_dict={"maxPwdAge": ["-155520000000000"]})]
    connections = iter([mock_conn, domain_conn])
    monkeypatch.setattr(ad_client, "_get_connection", lambda: next(connections))

    result = ad_client.get_password_expiry("jsmith@example.com")

    assert result["password_never_expires"] is True
    assert result["password_expires_at"] is None
    assert result["days_remaining"] is None


def test_get_password_expiry_uses_pso_when_present(monkeypatch):
    import ad_client

    monkeypatch.setattr(ad_client, "ad_configured", lambda: True)

    pso_dn = "CN=StrictPSO,CN=Password Settings Container,CN=System,DC=example,DC=com"

    user_conn = MagicMock()
    user_conn.entries = [_mock_user(pso_dn=pso_dn)]

    pso_conn = MagicMock()
    pso_conn.entries = [MagicMock(entry_attributes_as_dict={
        "msDS-MaximumPasswordAge": ["-77760000000000"],
        "name": ["StrictPSO"],
        "cn": ["StrictPSO"],
    })]

    connections = iter([user_conn, pso_conn])
    monkeypatch.setattr(ad_client, "_get_connection", lambda: next(connections))

    result = ad_client.get_password_expiry("jsmith@example.com")

    assert result["status"] == "ok"
    assert result["policy_source"] == "fine_grained"
    assert result["max_password_age_days"] == 90
