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


def test_ensure_team_membership_posts_the_service_account_as_a_member():
    resp = MagicMock(ok=True, status_code=201)
    resp.headers = {}
    with patch("retention_graph_client.requests.request", return_value=resp) as mock_request:
        import retention_graph_client as g
        g.ensure_team_membership("token", "team-1", "retention-svc@example.com")
    _method, url = mock_request.call_args[0]
    assert url == "https://graph.microsoft.com/v1.0/teams/team-1/members"
    body = mock_request.call_args.kwargs["json"]
    assert body["user@odata.bind"] == "https://graph.microsoft.com/v1.0/users('retention-svc@example.com')"


def test_ensure_team_membership_raises_on_failure():
    resp = MagicMock(ok=False, status_code=403, text="Forbidden")
    resp.headers = {}
    with patch("retention_graph_client.requests.request", return_value=resp):
        import retention_graph_client as g
        try:
            g.ensure_team_membership("token", "team-1", "retention-svc@example.com")
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


def test_resolve_drive_item_from_content_url_returns_none_on_404():
    # 404 means the driveItem behind this attachment is already gone — the same
    # "already deleted, treat as success" case delete_drive_item tolerates. The
    # retry loop depends on it: a message whose sibling attachment failed stays
    # undeleted, so the next cycle re-resolves the attachment this job already
    # deleted. Raising here would record a false failure and block that message
    # from ever being deleted.
    import retention_graph_client as g
    resp = MagicMock(ok=False, status_code=404, text="Not found")
    resp.headers = {}
    with patch("retention_graph_client.requests.request", return_value=resp):
        assert g.resolve_drive_item_from_content_url("token", "https://sp/missing") is None


def test_resolve_drive_item_from_content_url_raises_on_non_404_failure():
    import retention_graph_client as g
    resp = MagicMock(ok=False, status_code=403, text="Forbidden")
    resp.headers = {}
    with patch("retention_graph_client.requests.request", return_value=resp):
        try:
            g.resolve_drive_item_from_content_url("token", "https://sp/denied")
            assert False, "expected RetentionGraphError"
        except g.RetentionGraphError as exc:
            assert exc.status_code == 403


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


def test_list_channels_for_teams_batch_maps_responses_back_to_team_ids():
    import retention_graph_client as g
    batch_response = _ok_response({
        "responses": [
            {"id": "0", "status": 200, "body": {"value": [{"id": "c1", "displayName": "General"}]}},
            {"id": "1", "status": 200, "body": {"value": [{"id": "c2", "displayName": "Random"}]}},
        ],
    })
    with patch("retention_graph_client.requests.request", return_value=batch_response) as mock_request:
        result = g.list_channels_for_teams_batch("token", ["t1", "t2"])

    assert result == {
        "t1": [{"id": "c1", "name": "General"}],
        "t2": [{"id": "c2", "name": "Random"}],
    }
    call_kwargs = mock_request.call_args.kwargs
    sub_requests = call_kwargs["json"]["requests"]
    assert [r["url"] for r in sub_requests] == ["/teams/t1/channels", "/teams/t2/channels"]


def test_list_channels_for_teams_batch_treats_a_failed_sub_request_as_no_channels():
    import retention_graph_client as g
    batch_response = _ok_response({
        "responses": [
            {"id": "0", "status": 200, "body": {"value": [{"id": "c1", "displayName": "General"}]}},
            {"id": "1", "status": 403, "body": {"error": {"message": "Forbidden"}}},
        ],
    })
    with patch("retention_graph_client.requests.request", return_value=batch_response):
        result = g.list_channels_for_teams_batch("token", ["t1", "t2"])

    assert result == {"t1": [{"id": "c1", "name": "General"}], "t2": []}


def test_list_channels_for_teams_batch_chunks_at_twenty_teams_per_call():
    import retention_graph_client as g
    team_ids = [f"t{i}" for i in range(25)]
    empty_batch = _ok_response({"responses": []})
    with patch("retention_graph_client.requests.request", return_value=empty_batch) as mock_request:
        g.list_channels_for_teams_batch("token", team_ids)

    assert mock_request.call_count == 2
    first_call_requests = mock_request.call_args_list[0].kwargs["json"]["requests"]
    second_call_requests = mock_request.call_args_list[1].kwargs["json"]["requests"]
    assert len(first_call_requests) == 20
    assert len(second_call_requests) == 5


def test_list_channels_for_teams_batch_raises_on_batch_level_failure():
    import retention_graph_client as g
    resp = MagicMock(ok=False, status_code=500, text="Internal Server Error")
    resp.headers = {}
    with patch("retention_graph_client.requests.request", return_value=resp):
        try:
            g.list_channels_for_teams_batch("token", ["t1"])
            assert False, "expected RetentionGraphError"
        except g.RetentionGraphError as exc:
            assert exc.status_code == 500
