# backend/tests/test_retention_cleanup_job.py
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _job_with_stores():
    from retention_cleanup_job import RetentionCleanupJob
    from retention_policy_store import RetentionPolicyStore
    policy_store = RetentionPolicyStore(db_path=tempfile.mktemp(suffix=".db"))
    connection_store = MagicMock()
    connection_store.get_valid_token.return_value = "token"
    graph_module = MagicMock()
    job = RetentionCleanupJob(connection_store=connection_store, policy_store=policy_store, graph_module=graph_module)
    return job, policy_store, connection_store, graph_module


async def test_compute_preview_counts_messages_and_replies():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    graph_module.list_messages_older_than.return_value = [
        {"id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice", "attachments": [{"id": "a1", "content_url": "u"}]},
    ]
    graph_module.list_replies_older_than.return_value = []

    preview = await job.compute_preview(policy["id"])

    assert preview["messages_count"] == 1
    assert preview["attachments_count"] == 1
    assert preview["oldest_message_at"] == "2025-01-01T00:00:00Z"


async def test_run_cycle_skips_when_no_active_policies():
    job, _policy_store, connection_store, graph_module = _job_with_stores()
    await job.run_cycle()
    connection_store.get_valid_token.assert_not_called()
    graph_module.list_messages_older_than.assert_not_called()


async def test_run_cycle_deletes_messages_and_records_run():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {"id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice", "attachments": []},
    ]
    graph_module.list_replies_older_than.return_value = []

    await job.run_cycle()

    runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 1
    assert runs[0]["outcome"] == "ok"
    assert runs[0]["messages_deleted"] == 1
    graph_module.delete_message.assert_called_once_with("token", "team-1", "chan-1", "m1")


async def test_run_cycle_records_partial_when_one_message_delete_fails():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {"id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice", "attachments": []},
        {"id": "m2", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Bob", "attachments": []},
    ]
    graph_module.list_replies_older_than.return_value = []
    graph_module.delete_message.side_effect = [None, RuntimeError("boom")]

    await job.run_cycle()

    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert runs[0]["outcome"] == "partial"
    assert runs[0]["messages_deleted"] == 1
    deletions, _total = policy_store.list_deletions(run_id=runs[0]["id"], limit=10, offset=0)
    statuses = {d["item_id"]: d["status"] for d in deletions}
    assert statuses == {"m1": "deleted", "m2": "failed"}


async def test_run_cycle_marks_all_active_policies_failed_when_token_invalid():
    from retention_graph_connection import RetentionGraphConnectionError
    job, policy_store, connection_store, _graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    connection_store.get_valid_token.side_effect = RetentionGraphConnectionError("disconnected")

    await job.run_cycle()

    runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 1
    assert runs[0]["outcome"] == "failed"
    assert runs[0]["error"] == "token_invalid"


async def test_run_cycle_marks_all_active_policies_failed_when_token_fetch_raises_generic_error():
    # get_valid_token() is documented to raise RetentionGraphConnectionError, but the
    # real implementation's token refresh does a raw requests.post() with no
    # try/except around the network call, so a transient network failure can escape
    # as a plain exception (e.g. requests.exceptions.ConnectionError). run_cycle()
    # must still fail every active policy closed rather than let this bubble up
    # uncaught and silently skip writing any run rows for the whole cycle.
    job, policy_store, connection_store, _graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    connection_store.get_valid_token.side_effect = RuntimeError("connection reset")

    await job.run_cycle()

    runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 1
    assert runs[0]["outcome"] == "failed"
    assert runs[0]["error"] == "token_invalid"


async def test_run_cycle_fetches_token_once_for_multiple_active_policies():
    job, policy_store, connection_store, graph_module = _job_with_stores()
    policy_a = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_b = policy_store.create_policy(
        team_id="team-2", team_name="Sales", channel_id="chan-2", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy_a["id"])
    policy_store.confirm_policy(policy_b["id"])
    graph_module.list_messages_older_than.return_value = []
    graph_module.list_replies_older_than.return_value = []

    await job.run_cycle()

    assert connection_store.get_valid_token.call_count == 1
    runs_a, _total_a = policy_store.list_runs(policy_id=policy_a["id"], limit=10, offset=0)
    runs_b, _total_b = policy_store.list_runs(policy_id=policy_b["id"], limit=10, offset=0)
    assert runs_a[0]["outcome"] == "ok"
    assert runs_b[0]["outcome"] == "ok"


async def test_run_cycle_resolves_site_id_once_per_run_across_multiple_attachments():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {
            "id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice",
            "attachments": [{"id": "a1", "content_url": "u1"}, {"id": "a2", "content_url": "u2"}],
        },
        {
            "id": "m2", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Bob",
            "attachments": [{"id": "a3", "content_url": "u3"}],
        },
    ]
    graph_module.list_replies_older_than.return_value = []
    graph_module.resolve_team_site_id.return_value = "site-1"
    graph_module.resolve_drive_item_from_content_url.side_effect = lambda _t, url: f"drive-{url}"

    await job.run_cycle()

    assert graph_module.resolve_team_site_id.call_count == 1
    assert graph_module.delete_drive_item.call_count == 3
    graph_module.delete_drive_item.assert_any_call("token", "site-1", "drive-u1")
    graph_module.delete_drive_item.assert_any_call("token", "site-1", "drive-u2")
    graph_module.delete_drive_item.assert_any_call("token", "site-1", "drive-u3")
    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert runs[0]["outcome"] == "ok"
    assert runs[0]["attachments_deleted"] == 3


async def test_attachment_deletion_resolves_content_url_before_deleting_drive_item():
    # attachment["id"] is a Teams chatMessageAttachment id, not a SharePoint
    # driveItem id. delete_drive_item() swallows 404s, so deleting the wrong id
    # would look like a success and write a lying status="deleted" audit row.
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {
            "id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice",
            "attachments": [{"id": "attachment-id-1", "content_url": "https://sp/file1"}],
        },
    ]
    graph_module.list_replies_older_than.return_value = []
    graph_module.resolve_team_site_id.return_value = "site-1"
    graph_module.resolve_drive_item_from_content_url.return_value = "real-drive-item-1"

    call_order: list[str] = []
    graph_module.resolve_drive_item_from_content_url.side_effect = (
        lambda *_a, **_k: call_order.append("resolve") or "real-drive-item-1"
    )
    graph_module.delete_drive_item.side_effect = lambda *_a, **_k: call_order.append("delete")

    await job.run_cycle()

    graph_module.resolve_drive_item_from_content_url.assert_called_once_with("token", "https://sp/file1")
    graph_module.delete_drive_item.assert_called_once_with("token", "site-1", "real-drive-item-1")
    assert call_order == ["resolve", "delete"]
    # The attachment id must never be passed to delete_drive_item.
    assert "attachment-id-1" not in graph_module.delete_drive_item.call_args[0]
    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    deletions, _t = policy_store.list_deletions(run_id=runs[0]["id"], limit=10, offset=0)
    attachment_rows = [d for d in deletions if d["item_type"] == "attachment"]
    assert [(d["item_id"], d["status"]) for d in attachment_rows] == [("real-drive-item-1", "deleted")]


async def test_attachment_content_url_resolution_failure_is_recorded_as_failed():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {
            "id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice",
            "attachments": [{"id": "attachment-id-1", "content_url": "https://sp/file1"}],
        },
    ]
    graph_module.list_replies_older_than.return_value = []
    graph_module.resolve_team_site_id.return_value = "site-1"
    graph_module.resolve_drive_item_from_content_url.side_effect = RuntimeError("403 Forbidden")

    await job.run_cycle()

    graph_module.delete_drive_item.assert_not_called()
    # The owning message stays undeleted so it (and its attachment) reappear next cycle.
    graph_module.delete_message.assert_not_called()
    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert runs[0]["outcome"] == "partial"
    assert runs[0]["attachments_deleted"] == 0
    assert runs[0]["messages_deleted"] == 0
    deletions, _t = policy_store.list_deletions(run_id=runs[0]["id"], limit=10, offset=0)
    attachment_rows = [d for d in deletions if d["item_type"] == "attachment"]
    assert len(attachment_rows) == 1
    assert attachment_rows[0]["status"] == "failed"
    assert "403 Forbidden" in (attachment_rows[0]["error"] or "")


async def test_attachments_are_deleted_before_the_message_on_the_happy_path():
    # Attachment deletion must precede the message delete so a failing attachment can
    # still be retried next cycle (the aged-list filter hides soft-deleted messages).
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {
            "id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice",
            "attachments": [{"id": "a1", "content_url": "https://sp/file1"}],
        },
    ]
    graph_module.list_replies_older_than.return_value = []
    graph_module.resolve_team_site_id.return_value = "site-1"
    graph_module.resolve_drive_item_from_content_url.return_value = "drive-1"

    order: list[str] = []
    graph_module.delete_drive_item.side_effect = lambda *_a, **_k: order.append("attachment")
    graph_module.delete_message.side_effect = lambda *_a, **_k: order.append("message")

    await job.run_cycle()

    assert order == ["attachment", "message"]
    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert runs[0]["outcome"] == "ok"
    assert runs[0]["messages_deleted"] == 1
    assert runs[0]["attachments_deleted"] == 1
    deletions, _t = policy_store.list_deletions(run_id=runs[0]["id"], limit=10, offset=0)
    statuses = {(d["item_type"], d["item_id"]): d["status"] for d in deletions}
    assert statuses == {("attachment", "drive-1"): "deleted", ("message", "m1"): "deleted"}


async def test_message_is_not_deleted_when_one_of_its_attachments_fails():
    # Regression: list_messages_older_than filters out soft-deleted messages, so if the
    # message were deleted first and its attachment delete then failed, the SharePoint
    # file would never reappear in a later cycle and would leak permanently while the
    # run reported outcome="ok". The message must stay undeleted so the pair is retried.
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    aged_message = {
        "id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice",
        "attachments": [{"id": "a1", "content_url": "https://sp/file1"}],
    }
    graph_module.list_messages_older_than.return_value = [aged_message]
    graph_module.list_replies_older_than.return_value = []
    graph_module.resolve_team_site_id.return_value = "site-1"
    graph_module.resolve_drive_item_from_content_url.return_value = "drive-1"
    graph_module.delete_drive_item.side_effect = RuntimeError("423 Locked")

    await job.run_cycle()

    graph_module.delete_message.assert_not_called()
    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert runs[0]["outcome"] == "partial"
    assert runs[0]["messages_deleted"] == 0
    assert runs[0]["attachments_deleted"] == 0
    deletions, _t = policy_store.list_deletions(run_id=runs[0]["id"], limit=10, offset=0)
    # No message row at all: nothing was deleted, so nothing is claimed in the audit.
    assert [(d["item_type"], d["item_id"], d["status"]) for d in deletions] == [("attachment", "a1", "failed")]

    # Second cycle: because the message was never soft-deleted, Graph still returns it
    # in the aged list, and both the attachment and the message get retried together.
    graph_module.delete_drive_item.side_effect = None
    graph_module.delete_drive_item.reset_mock()
    graph_module.list_messages_older_than.return_value = [aged_message]
    job._already_ran_this_hour = lambda _policy_id: False  # bypass the per-hour gate

    await job.run_cycle()

    assert graph_module.delete_drive_item.call_count == 1
    graph_module.delete_message.assert_called_once_with("token", "team-1", "chan-1", "m1")
    runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 2
    assert runs[0]["outcome"] == "ok"
    assert runs[0]["messages_deleted"] == 1
    assert runs[0]["attachments_deleted"] == 1


async def test_reply_is_not_deleted_when_its_attachment_fails():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {"id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice", "attachments": []},
    ]
    graph_module.list_replies_older_than.return_value = [
        {
            "id": "r1", "parent_id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Bob",
            "attachments": [{"id": "a1", "content_url": "https://sp/file1"}],
        },
    ]
    graph_module.resolve_team_site_id.return_value = "site-1"
    graph_module.resolve_drive_item_from_content_url.side_effect = RuntimeError("403 Forbidden")

    await job.run_cycle()

    graph_module.delete_reply.assert_not_called()
    # The parent message has no attachments of its own, so it is still purged.
    graph_module.delete_message.assert_called_once_with("token", "team-1", "chan-1", "m1")
    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert runs[0]["outcome"] == "partial"
    assert runs[0]["messages_deleted"] == 1


async def test_replies_are_deleted_before_their_parent_message():
    # Deleting a reply whose root message is already gone is fragile, so each
    # message's aged replies must be purged before the message itself.
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {"id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice", "attachments": []},
    ]
    graph_module.list_replies_older_than.return_value = [
        {"id": "r1", "parent_id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Bob", "attachments": []},
        {"id": "r2", "parent_id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Cara", "attachments": []},
    ]
    order: list[str] = []
    graph_module.delete_reply.side_effect = lambda _t, _tm, _c, _p, reply_id: order.append(f"reply:{reply_id}")
    graph_module.delete_message.side_effect = lambda _t, _tm, _c, message_id: order.append(f"message:{message_id}")

    await job.run_cycle()

    assert order == ["reply:r1", "reply:r2", "message:m1"]
    assert graph_module.delete_reply.call_count == 2
    assert graph_module.delete_message.call_count == 1


async def test_run_cycle_skips_policy_already_run_this_hour():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = []
    graph_module.list_replies_older_than.return_value = []

    # Simulate a run that already happened during this UTC clock hour, exactly as a
    # previous leader would have left it behind before a re-election/cutover.
    run_id = policy_store.start_run(policy["id"])
    policy_store.finish_run(run_id, outcome="ok", messages_deleted=0, attachments_deleted=0)

    await job.run_cycle()

    runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 1
    assert runs[0]["id"] == run_id
    graph_module.list_messages_older_than.assert_not_called()


async def test_run_cycle_runs_policy_with_no_previous_runs():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = []
    graph_module.list_replies_older_than.return_value = []

    assert job._already_ran_this_hour(policy["id"]) is False
    await job.run_cycle()

    _runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 1


async def test_run_cycle_runs_policy_whose_last_run_was_a_previous_hour(monkeypatch):
    import retention_cleanup_job as job_module
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = []
    graph_module.list_replies_older_than.return_value = []

    run_id = policy_store.start_run(policy["id"])
    policy_store.finish_run(run_id, outcome="ok", messages_deleted=0, attachments_deleted=0)

    # Move "now" forward two hours so the seeded run falls in a previous clock hour.
    real_datetime = job_module.datetime
    later = real_datetime.now(timezone.utc) + timedelta(hours=2)

    class _ShiftedDatetime(real_datetime):  # type: ignore[misc, valid-type]
        @classmethod
        def now(cls, tz=None):
            return later

    monkeypatch.setattr(job_module, "datetime", _ShiftedDatetime)

    assert job._already_ran_this_hour(policy["id"]) is False
    await job.run_cycle()

    _runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 2


async def test_already_ran_this_hour_is_false_for_unparseable_started_at():
    job, policy_store, _connection_store, _graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    job._policy_store = MagicMock()
    job._policy_store.list_runs.return_value = ([{"started_at": "not-a-timestamp"}], 1)

    assert job._already_ran_this_hour(policy["id"]) is False
