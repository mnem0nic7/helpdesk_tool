from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _ok_response(payload):
    resp = MagicMock(ok=True, status_code=200)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


def test_list_teams_follows_next_link():
    page1 = _ok_response({"value": [{"id": "t1", "displayName": "Eng"}], "@odata.nextLink": "https://graph/next"})
    page2 = _ok_response({"value": [{"id": "t2", "displayName": "Ops"}]})
    with patch("retention_graph_client.requests.request", side_effect=[page1, page2]):
        import retention_graph_client as g
        teams = g.list_teams("token")
    assert teams == [{"id": "t1", "name": "Eng"}, {"id": "t2", "name": "Ops"}]


def test_list_messages_older_than_filters_by_cutoff_and_extracts_attachments():
    import retention_graph_client as g
    old_msg = {
        "id": "m1", "createdDateTime": "2025-01-01T00:00:00Z",
        "from": {"user": {"displayName": "Alice"}},
        "attachments": [{"id": "a1", "contentType": "reference", "contentUrl": "https://sp/file1"}],
    }
    new_msg = {"id": "m2", "createdDateTime": "2026-09-01T00:00:00Z", "from": {"user": {"displayName": "Bob"}}, "attachments": []}
    resp = _ok_response({"value": [old_msg, new_msg]})
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch("retention_graph_client.requests.request", return_value=resp):
        messages = g.list_messages_older_than("token", "team-1", "chan-1", cutoff)
    assert len(messages) == 1
    assert messages[0]["id"] == "m1"
    assert messages[0]["sender_or_author"] == "Alice"
    assert messages[0]["attachments"] == [{"id": "a1", "content_url": "https://sp/file1"}]


def test_list_replies_older_than_tags_parent_id():
    import retention_graph_client as g
    reply = {"id": "r1", "createdDateTime": "2025-01-01T00:00:00Z", "from": {"user": {"displayName": "Alice"}}, "attachments": []}
    resp = _ok_response({"value": [reply]})
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch("retention_graph_client.requests.request", return_value=resp):
        replies = g.list_replies_older_than("token", "team-1", "chan-1", "m1", cutoff)
    assert replies[0]["parent_id"] == "m1"


def test_delete_message_raises_retention_graph_error_on_failure():
    import retention_graph_client as g
    resp = MagicMock(ok=False, status_code=403, text="Forbidden")
    resp.headers = {}
    with patch("retention_graph_client.requests.request", return_value=resp):
        try:
            g.delete_message("token", "team-1", "chan-1", "m1")
            assert False, "expected RetentionGraphError"
        except g.RetentionGraphError as exc:
            assert exc.status_code == 403


def test_list_messages_older_than_excludes_already_soft_deleted():
    # Graph keeps returning soft-deleted messages forever; without this filter the
    # hourly job re-attempts deletes it already performed and never converges to 'ok'.
    import retention_graph_client as g
    deleted_msg = {
        "id": "m1", "createdDateTime": "2025-01-01T00:00:00Z", "deletedDateTime": "2025-06-01T00:00:00Z",
        "from": {"user": {"displayName": "Alice"}}, "attachments": [],
    }
    live_msg = {
        "id": "m2", "createdDateTime": "2025-01-01T00:00:00Z",
        "from": {"user": {"displayName": "Bob"}}, "attachments": [],
    }
    resp = _ok_response({"value": [deleted_msg, live_msg]})
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch("retention_graph_client.requests.request", return_value=resp):
        messages = g.list_messages_older_than("token", "team-1", "chan-1", cutoff)
    assert [m["id"] for m in messages] == ["m2"]


def test_list_messages_older_than_excludes_system_event_messages():
    import retention_graph_client as g
    system_msg = {
        "id": "m1", "createdDateTime": "2025-01-01T00:00:00Z", "messageType": "systemEventMessage",
        "from": None, "attachments": [],
    }
    live_msg = {
        "id": "m2", "createdDateTime": "2025-01-01T00:00:00Z", "messageType": "message",
        "from": {"user": {"displayName": "Bob"}}, "attachments": [],
    }
    resp = _ok_response({"value": [system_msg, live_msg]})
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch("retention_graph_client.requests.request", return_value=resp):
        messages = g.list_messages_older_than("token", "team-1", "chan-1", cutoff)
    assert [m["id"] for m in messages] == ["m2"]


def test_list_replies_older_than_excludes_deleted_and_system_replies():
    import retention_graph_client as g
    deleted_reply = {
        "id": "r1", "createdDateTime": "2025-01-01T00:00:00Z", "deletedDateTime": "2025-06-01T00:00:00Z",
        "from": {"user": {"displayName": "Alice"}}, "attachments": [],
    }
    system_reply = {
        "id": "r2", "createdDateTime": "2025-01-01T00:00:00Z", "messageType": "systemEventMessage",
        "from": None, "attachments": [],
    }
    live_reply = {
        "id": "r3", "createdDateTime": "2025-01-01T00:00:00Z",
        "from": {"user": {"displayName": "Bob"}}, "attachments": [],
    }
    resp = _ok_response({"value": [deleted_reply, system_reply, live_reply]})
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch("retention_graph_client.requests.request", return_value=resp):
        replies = g.list_replies_older_than("token", "team-1", "chan-1", "m1", cutoff)
    assert [r["id"] for r in replies] == ["r3"]


def test_encode_sharing_url_matches_microsofts_documented_encoding():
    import base64
    import retention_graph_client as g
    url = "https://contoso.sharepoint.com/sites/Eng/Shared Documents/report+final/a?b=c"
    encoded = g._encode_sharing_url(url)
    assert encoded.startswith("u!")
    assert "=" not in encoded
    assert "/" not in encoded[2:]
    assert "+" not in encoded[2:]
    # Round-trips back to the original URL once the substitutions/padding are undone.
    body = encoded[2:].replace("_", "/").replace("-", "+")
    body += "=" * (-len(body) % 4)
    assert base64.b64decode(body).decode("utf-8") == url


def test_resolve_drive_item_from_content_url_calls_shares_endpoint():
    import retention_graph_client as g
    resp = _ok_response({"id": "drive-item-99"})
    with patch("retention_graph_client.requests.request", return_value=resp) as mock_request:
        item_id = g.resolve_drive_item_from_content_url("token", "https://sp/file1")
    assert item_id == "drive-item-99"
    called_url = mock_request.call_args[0][1]
    expected_share_id = g._encode_sharing_url("https://sp/file1")
    assert f"/shares/{expected_share_id}/driveItem" in called_url
    assert "$select=id" in called_url


def test_resolve_drive_item_from_content_url_raises_on_failure():
    import retention_graph_client as g
    resp = MagicMock(ok=False, status_code=404, text="Not found")
    resp.headers = {}
    with patch("retention_graph_client.requests.request", return_value=resp):
        try:
            g.resolve_drive_item_from_content_url("token", "https://sp/missing")
            assert False, "expected RetentionGraphError"
        except g.RetentionGraphError as exc:
            assert exc.status_code == 404


def test_request_retries_on_429_then_succeeds(monkeypatch):
    import retention_graph_client as g
    monkeypatch.setattr(g.time, "sleep", lambda _seconds: None)
    throttled = MagicMock(ok=False, status_code=429)
    throttled.headers = {"Retry-After": "1"}
    success = MagicMock(ok=True, status_code=200)
    success.headers = {}
    with patch("retention_graph_client.requests.request", side_effect=[throttled, success]):
        resp = g._request("POST", "https://graph/x", "token")
    assert resp.ok is True
