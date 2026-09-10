# backend/tests/test_retention_graph_connection.py
from __future__ import annotations

import logging
import tempfile
import threading
import time
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


def test_refresh_lock_is_a_real_lock_and_is_held_during_the_refresh_call():
    """The lock must cover the whole check-then-refresh sequence, not just the write.

    Entra rotates refresh tokens, so two callers that both observe the stale row
    near the 2-minute buffer would redeem the same refresh token; the loser gets
    invalid_grant and calls mark_disconnected(), which has no compare-and-set and
    would clobber the winner's freshly saved 'connected' row.
    """
    store = _fresh_store()
    assert isinstance(store._refresh_lock, type(threading.Lock()))
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="old-refresh",
        access_token="stale-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        connected_by="ops@example.com",
    )
    held_during_refresh = []

    def _post(*_args, **_kwargs):
        held_during_refresh.append(store._refresh_lock.locked())
        resp = MagicMock(ok=True)
        resp.json.return_value = {"access_token": "new-access-token", "expires_in": 3600}
        return resp

    with patch("retention_graph_connection.requests.post", side_effect=_post):
        store.get_valid_token()

    assert held_during_refresh == [True]
    # Released afterwards, so the next caller isn't deadlocked.
    assert store._refresh_lock.locked() is False


def test_refresh_lock_is_released_when_the_refresh_fails():
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
    assert store._refresh_lock.locked() is False
    # And a second call still runs (it raises the disconnected error, not a deadlock).
    try:
        store.get_valid_token()
        assert False, "expected RetentionGraphConnectionError"
    except RetentionGraphConnectionError:
        pass


def test_concurrent_get_valid_token_callers_only_refresh_once():
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="old-refresh",
        access_token="stale-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        connected_by="ops@example.com",
    )
    post_calls: list[str] = []

    def _post(*_args, **kwargs):
        post_calls.append(kwargs["data"]["refresh_token"])
        # Widen the window so an unsynchronized second caller would observe the
        # still-stale row and issue its own redemption of the same refresh token.
        time.sleep(0.05)
        resp = MagicMock(ok=True)
        resp.json.return_value = {
            "access_token": "new-access-token", "refresh_token": "rotated-refresh", "expires_in": 3600,
        }
        return resp

    tokens: list[str] = []

    def _call():
        tokens.append(store.get_valid_token())

    with patch("retention_graph_connection.requests.post", side_effect=_post):
        threads = [threading.Thread(target=_call) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert len(post_calls) == 1
    assert tokens == ["new-access-token", "new-access-token"]
    assert store.get_connection()["refresh_token"] == "rotated-refresh"
    assert store.get_status()["status"] == "connected"


def test_refresh_logs_attempt_and_success(caplog):
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="old-refresh",
        access_token="stale-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        connected_by="ops@example.com",
    )
    mock_response = MagicMock(ok=True)
    mock_response.json.return_value = {"access_token": "new-access-token", "expires_in": 3600}
    with caplog.at_level(logging.INFO, logger="retention_graph_connection"):
        with patch("retention_graph_connection.requests.post", return_value=mock_response):
            store.get_valid_token()
    messages = [record.getMessage() for record in caplog.records]
    assert any("refreshing access token for retention-bot@movedocs.com" in m for m in messages)
    assert any("access token refreshed successfully" in m for m in messages)


def test_refresh_failure_is_logged_not_only_recorded_in_last_error(caplog):
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
    with caplog.at_level(logging.WARNING, logger="retention_graph_connection"):
        with patch("retention_graph_connection.requests.post", return_value=mock_response):
            try:
                store.get_valid_token()
            except RetentionGraphConnectionError:
                pass
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("invalid_grant" in m for m in warnings)


def test_missing_access_token_in_refresh_response_is_logged(caplog):
    from retention_graph_connection import RetentionGraphConnectionError
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="old-refresh",
        access_token="stale-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        connected_by="ops@example.com",
    )
    mock_response = MagicMock(ok=True)
    mock_response.json.return_value = {"expires_in": 3600}
    with caplog.at_level(logging.WARNING, logger="retention_graph_connection"):
        with patch("retention_graph_connection.requests.post", return_value=mock_response):
            try:
                store.get_valid_token()
                assert False, "expected RetentionGraphConnectionError"
            except RetentionGraphConnectionError:
                pass
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("missing access_token" in m for m in warnings)


def test_get_valid_token_raises_when_never_connected():
    from retention_graph_connection import RetentionGraphConnectionError
    store = _fresh_store()
    try:
        store.get_valid_token()
        assert False, "expected RetentionGraphConnectionError"
    except RetentionGraphConnectionError:
        pass
