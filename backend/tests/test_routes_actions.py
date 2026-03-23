from __future__ import annotations

import logging
from unittest.mock import MagicMock


def test_bulk_status_logs_transition_lookup_failure(test_client, monkeypatch, caplog):
    import routes_actions

    mock_client = MagicMock()
    mock_client.get_transitions.side_effect = RuntimeError("transition lookup exploded")
    mock_client.transition_issue.return_value = None
    monkeypatch.setattr(routes_actions, "_client", mock_client)

    with caplog.at_level(logging.ERROR):
        resp = test_client.post(
            "/api/tickets/bulk/status",
            headers={"host": "it-app.movedocs.com"},
            json={"keys": ["OIT-100"], "transition_id": "31"},
        )

    assert resp.status_code == 200
    assert resp.json() == [{"key": "OIT-100", "success": True}]
    assert any(
        "Bulk status transition lookup failed for OIT-100 via 31" in record.getMessage()
        for record in caplog.records
    )


def test_bulk_assign_logs_assignee_lookup_failure(test_client, monkeypatch, caplog):
    import routes_actions

    mock_client = MagicMock()
    mock_client.get_users_assignable.side_effect = RuntimeError("assignee lookup exploded")
    mock_client.assign_issue.return_value = None
    monkeypatch.setattr(routes_actions, "_client", mock_client)

    with caplog.at_level(logging.ERROR):
        resp = test_client.post(
            "/api/tickets/bulk/assign",
            headers={"host": "it-app.movedocs.com"},
            json={"keys": ["OIT-100"], "account_id": "acct-123"},
        )

    assert resp.status_code == 200
    assert resp.json() == [{"key": "OIT-100", "success": True}]
    assert any(
        "Bulk assignee lookup failed for acct-123 in project" in record.getMessage()
        for record in caplog.records
    )


def test_bulk_priority_logs_per_ticket_failure(test_client, monkeypatch, caplog):
    import routes_actions

    mock_client = MagicMock()
    mock_client.update_priority.side_effect = RuntimeError("priority update exploded")
    monkeypatch.setattr(routes_actions, "_client", mock_client)

    with caplog.at_level(logging.ERROR):
        resp = test_client.post(
            "/api/tickets/bulk/priority",
            headers={"host": "it-app.movedocs.com"},
            json={"keys": ["OIT-100"], "priority": "High"},
        )

    assert resp.status_code == 200
    assert resp.json() == [{"key": "OIT-100", "success": False, "error": "priority update exploded"}]
    assert any(
        "Bulk priority update failed for OIT-100 to High" in record.getMessage()
        for record in caplog.records
    )

