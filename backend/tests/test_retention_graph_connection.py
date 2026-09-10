# backend/tests/test_retention_graph_connection.py
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _fresh_store():
    from retention_graph_connection import RetentionGraphConnectionStore
    return RetentionGraphConnectionStore(db_path=tempfile.mktemp(suffix=".db"))


def test_get_connection_returns_none_when_unset():
    store = _fresh_store()
    assert store.get_connection() is None
    assert store.get_status() == {
        "status": "disconnected", "service_account_upn": "", "last_refreshed_at": None, "last_error": None,
    }


def test_save_and_get_connection_round_trips_and_encrypts_refresh_token():
    store = _fresh_store()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="raw-refresh-token",
        access_token="raw-access-token",
        access_token_expires_at=expires_at,
        connected_by="ops@example.com",
    )
    with store._sqlite_conn() as conn:
        row = conn.execute("SELECT encrypted_refresh_token FROM retention_graph_connection WHERE id = 1").fetchone()
    assert "raw-refresh-token" not in row["encrypted_refresh_token"]

    connection = store.get_connection()
    assert connection["service_account_upn"] == "retention-bot@movedocs.com"
    assert connection["refresh_token"] == "raw-refresh-token"
    assert connection["status"] == "connected"


def test_get_valid_token_returns_cached_token_when_not_near_expiry():
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="rt",
        access_token="cached-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        connected_by="ops@example.com",
    )
    with patch("retention_graph_connection.requests") as mock_requests:
        token = store.get_valid_token()
    assert token == "cached-access-token"
    mock_requests.post.assert_not_called()


def test_get_valid_token_refreshes_when_near_expiry():
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="old-refresh",
        access_token="stale-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        connected_by="ops@example.com",
    )
    mock_response = MagicMock(ok=True)
    mock_response.json.return_value = {"access_token": "new-access-token", "refresh_token": "new-refresh", "expires_in": 3600}
    with patch("retention_graph_connection.requests.post", return_value=mock_response):
        token = store.get_valid_token()
    assert token == "new-access-token"
    assert store.get_connection()["refresh_token"] == "new-refresh"


def test_get_valid_token_marks_disconnected_on_refresh_failure():
    from retention_graph_connection import RetentionGraphConnectionError
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="old-refresh",
        access_token="stale-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        connected_by="ops@example.com",
    )
    mock_response = MagicMock(ok=False, status_code=400, text="invalid_grant")
    with patch("retention_graph_connection.requests.post", return_value=mock_response):
        try:
            store.get_valid_token()
            assert False, "expected RetentionGraphConnectionError"
        except RetentionGraphConnectionError:
            pass
    assert store.get_status()["status"] == "disconnected"


def test_get_valid_token_raises_when_never_connected():
    from retention_graph_connection import RetentionGraphConnectionError
    store = _fresh_store()
    try:
        store.get_valid_token()
        assert False, "expected RetentionGraphConnectionError"
    except RetentionGraphConnectionError:
        pass
