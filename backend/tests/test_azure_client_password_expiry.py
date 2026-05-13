from unittest.mock import MagicMock, patch
import pytest


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
