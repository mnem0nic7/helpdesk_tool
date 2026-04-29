"""Unit tests for the new AD offboarding helpers in ad_client.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(sam: str = "jdoe", dn: str = "CN=Jane Doe,OU=Staff,DC=oasislegal,DC=com") -> dict:
    return {
        "sam": sam,
        "dn": dn,
        "display_name": "Jane Doe",
        "enabled": True,
        "member_of": [],
    }


# ---------------------------------------------------------------------------
# update_termination_attributes
# ---------------------------------------------------------------------------

def test_update_termination_attributes_modifies_correct_attrs(monkeypatch):
    import ad_client

    user = _make_user()
    mock_conn = MagicMock()
    mock_conn.result = {"result": 0}
    mock_conn.entries = []

    monkeypatch.setattr(ad_client, "get_user", lambda sam: user)
    monkeypatch.setattr(ad_client, "_get_connection", lambda: mock_conn)

    result = ad_client.update_termination_attributes("jdoe")

    assert mock_conn.modify.call_count == 1
    call_args = mock_conn.modify.call_args
    dn_arg, changes_arg = call_args[0]
    assert dn_arg == user["dn"]

    assert "telephoneNumber" in changes_arg
    assert "mailNickname" in changes_arg
    assert "physicalDeliveryOfficeName" in changes_arg
    assert "msExchAssistantName" in changes_arg
    assert "terminationDate" in changes_arg
    assert "msExchHideFromAddressLists" in changes_arg
    assert "msDS-cloudExtensionAttribute1" in changes_arg
    assert "manager" in changes_arg
    assert "department" in changes_arg

    assert result["mailNickname"] == "jdoe"
    assert result["physicalDeliveryOfficeName"] == "DISABLED"
    assert result["msExchAssistantName"] == "HideFromGAL"
    assert result["msExchHideFromAddressLists"] == "TRUE"
    assert result["telephoneNumber"] == ""
    assert result["manager"] == ""
    assert result["department"] == ""

    mock_conn.unbind.assert_called_once()


def test_update_termination_attributes_raises_on_ldap_failure(monkeypatch):
    import ad_client
    from ad_client import ADError

    user = _make_user()
    mock_conn = MagicMock()
    mock_conn.result = {"result": 53, "description": "unwilling to perform"}

    monkeypatch.setattr(ad_client, "get_user", lambda sam: user)
    monkeypatch.setattr(ad_client, "_get_connection", lambda: mock_conn)

    try:
        ad_client.update_termination_attributes("jdoe")
        assert False, "Should have raised ADError"
    except ADError as exc:
        assert "unwilling" in str(exc).lower() or "Termination" in str(exc)


# ---------------------------------------------------------------------------
# remove_from_all_groups_except_domain_users
# ---------------------------------------------------------------------------

def test_remove_from_all_groups_skips_domain_users(monkeypatch):
    import ad_client

    user = _make_user()
    user["member_of"] = [
        "CN=Domain Users,CN=Users,DC=oasislegal,DC=com",
        "CN=ITStaff,OU=Groups,DC=oasislegal,DC=com",
    ]

    mock_conn = MagicMock()
    mock_conn.entries = []

    def fake_group_sam_from_dn(dn: str) -> str:
        if "ITStaff" in dn:
            return "ITStaff"
        return ""

    monkeypatch.setattr(ad_client, "get_user", lambda sam: user)
    monkeypatch.setattr(ad_client, "_group_sam_from_dn", fake_group_sam_from_dn)
    monkeypatch.setattr(ad_client, "remove_group_member", lambda group_sam, user_dn: None)

    result = ad_client.remove_from_all_groups_except_domain_users("jdoe")

    assert "Domain Users" in result["skipped"]
    assert "ITStaff" in result["removed"]
    assert result["failures"] == []


def test_remove_from_all_groups_records_failures_on_remove_error(monkeypatch):
    import ad_client
    from ad_client import ADError

    user = _make_user()
    user["member_of"] = ["CN=Finance,OU=Groups,DC=oasislegal,DC=com"]

    def fake_group_sam_from_dn(dn: str) -> str:
        return "Finance"

    def failing_remove(group_sam: str, user_dn: str) -> None:
        raise ADError("insufficient access rights")

    monkeypatch.setattr(ad_client, "get_user", lambda sam: user)
    monkeypatch.setattr(ad_client, "_group_sam_from_dn", fake_group_sam_from_dn)
    monkeypatch.setattr(ad_client, "remove_group_member", failing_remove)

    result = ad_client.remove_from_all_groups_except_domain_users("jdoe")

    assert result["failures"] != []
    assert result["removed"] == []


def test_remove_from_all_groups_records_failure_when_group_sam_unknown(monkeypatch):
    import ad_client

    user = _make_user()
    user["member_of"] = ["CN=Mystery,OU=Groups,DC=oasislegal,DC=com"]

    monkeypatch.setattr(ad_client, "get_user", lambda sam: user)
    monkeypatch.setattr(ad_client, "_group_sam_from_dn", lambda dn: "")

    result = ad_client.remove_from_all_groups_except_domain_users("jdoe")

    assert len(result["failures"]) == 1
    assert result["removed"] == []


# ---------------------------------------------------------------------------
# move_to_disabled_users_ou
# ---------------------------------------------------------------------------

def test_move_to_disabled_users_ou_calls_move_object(monkeypatch):
    import ad_client

    user = _make_user(dn="CN=Jane Doe,OU=Staff,DC=oasislegal,DC=com")

    moved: list[tuple] = []

    def fake_move(src_dn: str, dest_ou: str) -> None:
        moved.append((src_dn, dest_ou))

    monkeypatch.setattr(ad_client, "get_user", lambda sam: user)
    monkeypatch.setattr(ad_client, "move_object", fake_move)
    monkeypatch.setattr(ad_client, "DISABLED_USERS_OU_DN", "OU=Disabled Users,DC=oasislegal,DC=com")

    new_dn = ad_client.move_to_disabled_users_ou("jdoe")

    assert len(moved) == 1
    assert moved[0][0] == user["dn"]
    assert "Disabled Users" in moved[0][1]
    assert new_dn.startswith("CN=Jane Doe")
    assert "Disabled Users" in new_dn


def test_move_to_disabled_users_ou_raises_when_ou_not_configured(monkeypatch):
    import ad_client
    from ad_client import ADError

    user = _make_user()
    monkeypatch.setattr(ad_client, "get_user", lambda sam: user)
    monkeypatch.setattr(ad_client, "DISABLED_USERS_OU_DN", "")

    try:
        ad_client.move_to_disabled_users_ou("jdoe")
        assert False, "Should have raised ADError"
    except ADError as exc:
        assert "not configured" in str(exc).lower()


# ---------------------------------------------------------------------------
# reset_password_random
# ---------------------------------------------------------------------------

def test_reset_password_random_returns_complex_password(monkeypatch):
    import ad_client
    import string

    monkeypatch.setattr(ad_client, "AD_USE_SSL", True)

    reset_calls: list[tuple] = []

    def fake_reset(sam: str, pw: str, must_change: bool) -> None:
        reset_calls.append((sam, pw, must_change))

    monkeypatch.setattr(ad_client, "reset_password", fake_reset)

    pw = ad_client.reset_password_random("jdoe")

    assert len(pw) == 20
    assert any(c in string.ascii_uppercase for c in pw)
    assert any(c in string.ascii_lowercase for c in pw)
    assert any(c in string.digits for c in pw)
    assert any(c in "!@#$%^&*" for c in pw)

    assert len(reset_calls) == 1
    sam_arg, pw_arg, must_change_arg = reset_calls[0]
    assert sam_arg == "jdoe"
    assert pw_arg == pw
    assert must_change_arg is False


def test_reset_password_random_raises_without_ssl(monkeypatch):
    import ad_client
    from ad_client import ADError

    monkeypatch.setattr(ad_client, "AD_USE_SSL", False)

    try:
        ad_client.reset_password_random("jdoe")
        assert False, "Should have raised ADError"
    except ADError as exc:
        assert "SSL" in str(exc) or "LDAPS" in str(exc)
