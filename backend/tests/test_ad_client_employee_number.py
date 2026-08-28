"""Unit tests for employeeNumber read/write support in ad_client.py."""

from __future__ import annotations

from unittest.mock import MagicMock


def _mock_entry(employee_number: str = "26LUA0GGA"):
    entry = MagicMock()
    entry.entry_attributes_as_dict = {
        "sAMAccountName": ["gallison"],
        "userPrincipalName": ["gallison@example.com"],
        "displayName": ["Grant Allison"],
        "givenName": ["Grant"], "sn": ["Allison"],
        "mail": ["gallison@example.com"],
        "userAccountControl": ["512"],
        "employeeNumber": [employee_number] if employee_number else [],
        "telephoneNumber": [], "mobile": [], "department": [], "title": [],
        "manager": [], "description": [], "streetAddress": [], "l": [], "st": [],
        "postalCode": [], "co": [], "company": [], "employeeID": [],
        "accountExpires": [], "pwdLastSet": [], "lastLogonTimestamp": [],
        "lockoutTime": [], "badPwdCount": ["0"], "memberOf": [],
        "whenCreated": [], "whenChanged": [], "msDS-ResultantPSO": [],
    }
    entry.entry_dn = "CN=Grant Allison,DC=example,DC=com"
    return entry


def test_entry_to_user_exposes_current_employee_number():
    import ad_client

    user = ad_client._entry_to_user(_mock_entry("26LUA0GGA"))

    assert user["employee_number"] == "26LUA0GGA"


def test_entry_to_user_employee_number_blank_when_unset():
    import ad_client

    user = ad_client._entry_to_user(_mock_entry(""))

    assert user["employee_number"] == ""


def test_user_attrs_includes_employee_number():
    import ad_client

    assert "employeeNumber" in ad_client._USER_ATTRS


def test_update_user_writes_employee_number(monkeypatch):
    import ad_client

    user = {"dn": "CN=Grant Allison,DC=example,DC=com"}
    mock_conn = MagicMock()
    mock_conn.result = {"result": 0}

    monkeypatch.setattr(ad_client, "get_user", lambda sam: user)
    monkeypatch.setattr(ad_client, "_get_connection", lambda: mock_conn)

    ad_client.update_user("gallison", {"employeeNumber": "26LUA0GGA"})

    assert mock_conn.modify.call_count == 1
    dn_arg, changes_arg = mock_conn.modify.call_args[0]
    assert dn_arg == user["dn"]
    assert "employeeNumber" in changes_arg
