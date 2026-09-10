from __future__ import annotations

import tempfile


def _fresh_store():
    from retention_policy_store import RetentionPolicyStore
    return RetentionPolicyStore(db_path=tempfile.mktemp(suffix=".db"))


def test_create_policy_starts_pending_preview():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    assert policy["status"] == "pending_preview"
    assert policy["retention_days"] == 30
    assert store.get_policy_for_channel("team-1", "chan-1")["id"] == policy["id"]


def test_confirm_policy_sets_active():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    confirmed = store.confirm_policy(policy["id"])
    assert confirmed["status"] == "active"
    assert [p["id"] for p in store.list_active_policies()] == [policy["id"]]


def test_update_policy_retention_days_resets_to_pending_preview():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    store.confirm_policy(policy["id"])
    updated = store.update_policy(policy["id"], retention_days=60)
    assert updated["status"] == "pending_preview"
    assert updated["retention_days"] == 60
    assert store.list_active_policies() == []


def test_update_policy_status_disable_does_not_reset_days():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    store.confirm_policy(policy["id"])
    updated = store.update_policy(policy["id"], status="disabled")
    assert updated["status"] == "disabled"
    assert updated["retention_days"] == 30


def test_run_and_deletion_lifecycle():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    run_id = store.start_run(policy["id"])
    store.record_deletion(
        run_id=run_id, item_type="message", item_id="msg-1", sender_or_author="Alice",
        original_created_at="2026-01-01T00:00:00Z", status="deleted",
    )
    store.record_deletion(
        run_id=run_id, item_type="attachment", item_id="att-1", sender_or_author="Alice",
        original_created_at="2026-01-01T00:00:00Z", status="failed", error="not found",
    )
    store.finish_run(run_id, outcome="partial", messages_deleted=1, attachments_deleted=0, error=None)

    runs, total_runs = store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total_runs == 1
    assert runs[0]["outcome"] == "partial"
    assert runs[0]["messages_deleted"] == 1

    deletions, total_deletions = store.list_deletions(run_id=run_id, limit=10, offset=0)
    assert total_deletions == 2
    statuses = {d["item_id"]: d["status"] for d in deletions}
    assert statuses == {"msg-1": "deleted", "att-1": "failed"}
