from __future__ import annotations

import security_application_hygiene


class _StubAzureCache:
    def __init__(self, snapshots, status_payload):
        self._snapshots = snapshots
        self._status_payload = status_payload

    def _snapshot(self, key):
        return self._snapshots.get(key, [])

    def status(self):
        return self._status_payload


def _status_payload():
    return {
        "configured": True,
        "initialized": True,
        "refreshing": False,
        "datasets": [
            {"key": "directory", "label": "Identity", "last_refresh": "2026-04-02T01:00:00Z"},
        ],
    }


def test_build_security_application_hygiene_flags_expired_credentials_and_missing_owners(monkeypatch):
    snapshots = {
        "application_security": [
            {
                "id": "app-1",
                "app_id": "00000000-1111-2222-3333-444444444444",
                "display_name": "Payroll Connector",
                "sign_in_audience": "AzureADMyOrg",
                "created_datetime": "2024-01-10T00:00:00Z",
                "publisher_domain": "contoso.com",
                "verified_publisher_name": "",
                "owner_count": 0,
                "owners": [],
                "owner_lookup_error": "",
                "credential_count": 2,
                "password_credential_count": 1,
                "key_credential_count": 1,
                "next_credential_expiry": "2026-04-05T00:00:00Z",
                "credentials": [
                    {
                        "credential_type": "secret",
                        "display_name": "Prod secret",
                        "key_id": "secret-1",
                        "start_date_time": "2025-01-01T00:00:00Z",
                        "end_date_time": "2026-03-01T00:00:00Z",
                    },
                    {
                        "credential_type": "certificate",
                        "display_name": "Prod cert",
                        "key_id": "cert-1",
                        "start_date_time": "2025-01-01T00:00:00Z",
                        "end_date_time": "2026-04-05T00:00:00Z",
                    },
                ],
            },
            {
                "id": "app-2",
                "app_id": "55555555-6666-7777-8888-999999999999",
                "display_name": "External Intake",
                "sign_in_audience": "AzureADandPersonalMicrosoftAccount",
                "created_datetime": "2025-01-10T00:00:00Z",
                "publisher_domain": "fabrikam.com",
                "verified_publisher_name": "",
                "owner_count": 1,
                "owners": [{"display_name": "Ada Lovelace", "principal_name": "ada@example.com"}],
                "owner_lookup_error": "",
                "credential_count": 1,
                "password_credential_count": 1,
                "key_credential_count": 0,
                "next_credential_expiry": "2026-04-20T00:00:00Z",
                "credentials": [
                    {
                        "credential_type": "secret",
                        "display_name": "External secret",
                        "key_id": "secret-2",
                        "start_date_time": "2025-01-01T00:00:00Z",
                        "end_date_time": "2026-04-20T00:00:00Z",
                    }
                ],
            },
        ]
    }
    monkeypatch.setattr(
        security_application_hygiene,
        "azure_cache",
        _StubAzureCache(snapshots, _status_payload()),
    )

    response = security_application_hygiene.build_security_application_hygiene()

    assert response.metrics[0].value == 2
    assert response.metrics[1].value == 1
    assert response.metrics[2].value >= 1
    assert response.metrics[3].value == 1
    assert response.metrics[4].value == 1
    payroll = next(item for item in response.flagged_apps if item.application_id == "app-1")
    assert payroll.status == "critical"
    assert any("expired" in flag.lower() for flag in payroll.flags)
    assert any("owners" in flag.lower() for flag in payroll.flags)
    external = next(item for item in response.flagged_apps if item.application_id == "app-2")
    assert any("outside the home tenant" in flag.lower() for flag in external.flags)
    assert any("verified publisher" in flag.lower() for flag in external.flags)
    assert response.credentials[0].status in {"expired", "expiring"}


def test_build_security_application_hygiene_warns_when_rich_snapshot_is_not_ready(monkeypatch):
    snapshots = {
        "application_security": [],
        "applications": [
            {
                "id": "app-1",
                "display_name": "Fallback App",
                "app_id": "00000000-1111-2222-3333-444444444444",
                "extra": {
                    "sign_in_audience": "AzureADMyOrg",
                    "created_datetime": "2025-01-10T00:00:00Z",
                    "publisher_domain": "contoso.com",
                    "verified_publisher_name": "",
                    "owner_count": "0",
                    "credential_count": "0",
                },
            }
        ],
    }
    monkeypatch.setattr(
        security_application_hygiene,
        "azure_cache",
        _StubAzureCache(snapshots, _status_payload()),
    )

    response = security_application_hygiene.build_security_application_hygiene()

    assert response.metrics[0].value == 1
    assert any("upgraded collector" in warning for warning in response.warnings)
