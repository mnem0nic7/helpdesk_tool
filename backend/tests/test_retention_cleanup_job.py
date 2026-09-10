# backend/tests/test_retention_cleanup_job.py
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
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

    await job.run_cycle()

    assert graph_module.resolve_team_site_id.call_count == 1
    assert graph_module.delete_drive_item.call_count == 3
    graph_module.delete_drive_item.assert_any_call("token", "site-1", "a1")
    graph_module.delete_drive_item.assert_any_call("token", "site-1", "a2")
    graph_module.delete_drive_item.assert_any_call("token", "site-1", "a3")
    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert runs[0]["outcome"] == "ok"
    assert runs[0]["attachments_deleted"] == 3
