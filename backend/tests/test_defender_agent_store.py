"""Tests for DefenderAgentStore — config, runs, decisions, pending T2, summary."""
from __future__ import annotations

from pathlib import Path

from defender_agent_store import DefenderAgentStore


def _store(tmp_path: Path) -> DefenderAgentStore:
    return DefenderAgentStore(db_path=str(tmp_path / "defender.db"))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_get_config_returns_defaults(tmp_path):
    store = _store(tmp_path)
    cfg = store.get_config()
    assert "enabled" in cfg
    assert "min_severity" in cfg
    assert "tier2_delay_minutes" in cfg


def test_upsert_config_persists(tmp_path):
    store = _store(tmp_path)
    store.upsert_config(enabled=False, min_severity="critical", tier2_delay_minutes=30, dry_run=True)
    cfg = store.get_config()
    assert cfg["enabled"] is False
    assert cfg["min_severity"] == "critical"
    assert cfg["tier2_delay_minutes"] == 30
    assert cfg["dry_run"] is True


def test_upsert_config_updated_by(tmp_path):
    store = _store(tmp_path)
    defaults = store.get_config()
    store.upsert_config(
        enabled=True,
        min_severity=defaults["min_severity"],
        tier2_delay_minutes=defaults["tier2_delay_minutes"],
        dry_run=False,
        updated_by="admin@example.com",
    )
    cfg = store.get_config()
    assert cfg["updated_by"] == "admin@example.com"


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def test_create_and_list_runs(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run-1"
    assert runs[0]["completed_at"] is None


def test_complete_run_updates_stats(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    store.complete_run("run-1", alerts_fetched=5, alerts_new=3, decisions_made=3, actions_queued=2)
    runs = store.list_runs()
    r = runs[0]
    assert r["alerts_fetched"] == 5
    assert r["decisions_made"] == 3
    assert r["actions_queued"] == 2
    assert r["completed_at"] is not None


def test_complete_run_records_error(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-err")
    store.complete_run("run-err", alerts_fetched=0, alerts_new=0, decisions_made=0, actions_queued=0, error="Graph timeout")
    runs = store.list_runs()
    assert runs[0]["error"] == "Graph timeout"


def test_list_runs_returns_most_recent_first(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-a")
    store.create_run("run-b")
    runs = store.list_runs()
    assert runs[0]["run_id"] == "run-b"


# ---------------------------------------------------------------------------
# Decisions — CRUD
# ---------------------------------------------------------------------------

def _make_decision(store: DefenderAgentStore, *, decision_id: str = "dec-1", tier: int = 1,
                   decision: str = "execute", action_type: str = "revoke_sessions",
                   action_types: list | None = None) -> dict:
    return store.create_decision(
        decision_id=decision_id,
        run_id="run-1",
        alert_id="ext-alert-1",
        alert_title="Suspicious Sign-In",
        alert_severity="high",
        alert_category="SuspiciousActivity",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForIdentity",
        tier=tier,
        decision=decision,
        action_type=action_type,
        action_types=action_types or [action_type],
        job_ids=[],
        reason="Test reason",
        entities=[{"type": "user", "id": "user-1", "name": "ada@example.com"}],
        not_before_at=None,
    )


def test_create_and_get_decision(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store)
    dec = store.get_decision("dec-1")
    assert dec is not None
    assert dec["decision_id"] == "dec-1"
    assert dec["decision"] == "execute"
    assert dec["action_type"] == "revoke_sessions"
    assert dec["tier"] == 1


def test_get_decision_not_found_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.get_decision("nonexistent") is None


def test_create_decision_composite_action_types(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(
        store,
        decision="queue",
        action_type="isolate_device",
        action_types=["isolate_device", "revoke_sessions"],
        tier=2,
    )
    dec = store.get_decision("dec-1")
    assert "isolate_device" in dec["action_types"]
    assert "revoke_sessions" in dec["action_types"]


def test_list_decisions_returns_all(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision_id="dec-1")
    _make_decision(store, decision_id="dec-2", action_type="device_sync")
    decisions, total = store.list_decisions()
    assert total == 2
    assert len(decisions) == 2


def test_list_decisions_pagination(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    for i in range(5):
        _make_decision(store, decision_id=f"dec-{i}")
    decisions, total = store.list_decisions(limit=2, offset=0)
    assert total == 5
    assert len(decisions) == 2


def test_update_decision_jobs(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store)
    store.update_decision_jobs("dec-1", ["job-a", "job-b"])
    dec = store.get_decision("dec-1")
    assert "job-a" in dec["job_ids"]
    assert "job-b" in dec["job_ids"]


# ---------------------------------------------------------------------------
# Cancel / Approve
# ---------------------------------------------------------------------------

def test_cancel_decision(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision="queue", tier=2)
    result = store.cancel_decision("dec-1", cancelled_by="operator@example.com")
    assert result is not None
    assert result["cancelled"] is True


def test_cancel_is_idempotent_returns_decision(tmp_path):
    """cancel_decision returns the decision regardless; route enforces 409 on repeat cancels."""
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision="queue", tier=2)
    store.cancel_decision("dec-1", cancelled_by="op@example.com")
    result = store.cancel_decision("dec-1", cancelled_by="op@example.com")
    assert result is not None
    assert result["cancelled"] is True


def test_approve_decision(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision="recommend", tier=3)
    result = store.approve_decision("dec-1", approved_by="admin@example.com")
    assert result is not None
    assert result["human_approved"] is True


# ---------------------------------------------------------------------------
# Seen alert IDs
# ---------------------------------------------------------------------------

def test_get_seen_alert_ids(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision_id="dec-1")
    seen = store.get_seen_alert_ids()
    assert "ext-alert-1" in seen


def test_get_seen_alert_ids_empty_when_no_decisions(tmp_path):
    store = _store(tmp_path)
    assert store.get_seen_alert_ids() == set()


# ---------------------------------------------------------------------------
# Pending T2
# ---------------------------------------------------------------------------

def _make_t2_decision(store: DefenderAgentStore, decision_id: str = "dec-t2",
                      not_before_at: str = "2026-01-01T00:00:00Z") -> dict:
    return store.create_decision(
        decision_id=decision_id,
        run_id="run-1",
        alert_id=f"ext-{decision_id}",
        alert_title="Password Spray",
        alert_severity="high",
        alert_category="CredentialAccess",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForIdentity",
        tier=2,
        decision="queue",
        action_type="disable_sign_in",
        action_types=["disable_sign_in"],
        job_ids=[],
        reason="Queued by agent",
        entities=[],
        not_before_at=not_before_at,
    )


def test_list_pending_tier2_returns_past_due_decisions(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_t2_decision(store)  # not_before_at in the past
    pending = store.list_pending_tier2()
    assert any(d["decision_id"] == "dec-t2" for d in pending)


def test_list_pending_tier2_excludes_future_not_before_at(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_t2_decision(store, not_before_at="2099-01-01T00:00:00Z")
    pending = store.list_pending_tier2()
    assert not any(d["decision_id"] == "dec-t2" for d in pending)


def test_list_pending_tier2_excludes_cancelled(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_t2_decision(store)
    store.cancel_decision("dec-t2")
    pending = store.list_pending_tier2()
    assert not any(d["decision_id"] == "dec-t2" for d in pending)


def test_list_pending_tier2_excludes_executed_t1(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision_id="dec-t1", decision="execute", tier=1)
    pending = store.list_pending_tier2()
    assert not any(d["decision_id"] == "dec-t1" for d in pending)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_get_summary_returns_expected_keys(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    store.complete_run("run-1", alerts_fetched=3, alerts_new=2, decisions_made=2, actions_queued=1)
    _make_decision(store, decision_id="dec-exec", decision="execute", tier=1)
    _make_decision(store, decision_id="dec-rec", decision="recommend", tier=3)

    summary = store.get_summary()
    assert "enabled" in summary
    assert "last_run_at" in summary
    assert "pending_approvals" in summary
    assert "pending_tier2" in summary
    assert "recent_decisions" in summary
    # The T3 recommend decision is not yet approved → pending_approvals == 1
    assert summary["pending_approvals"] == 1
    # Recent decisions populated
    assert len(summary["recent_decisions"]) >= 2


# ---------------------------------------------------------------------------
# Suppressions
# ---------------------------------------------------------------------------

def test_create_suppression_persists(tmp_path):
    store = _store(tmp_path)
    row = store.create_suppression(
        suppression_type="entity_user",
        value="ada@example.com",
        reason="Known good test account",
        created_by="admin@example.com",
    )
    assert row["suppression_type"] == "entity_user"
    assert row["value"] == "ada@example.com"
    assert row["reason"] == "Known good test account"
    assert row["active"] is True
    assert row["expires_at"] is None


def test_create_suppression_with_expiry(tmp_path):
    store = _store(tmp_path)
    row = store.create_suppression(
        suppression_type="alert_title",
        value="test alert",
        expires_at="2099-01-01T00:00:00Z",
    )
    assert row["expires_at"] == "2099-01-01T00:00:00Z"


def test_list_suppressions_active_only(tmp_path):
    store = _store(tmp_path)
    store.create_suppression(suppression_type="entity_user", value="user1@example.com")
    store.create_suppression(suppression_type="entity_device", value="DEVICE-001")
    rows = store.list_suppressions()
    assert len(rows) == 2


def test_list_suppressions_excludes_expired(tmp_path):
    store = _store(tmp_path)
    store.create_suppression(suppression_type="entity_user", value="user-forever@example.com")
    store.create_suppression(
        suppression_type="entity_user",
        value="user-expired@example.com",
        expires_at="2000-01-01T00:00:00Z",
    )
    rows = store.list_suppressions()
    values = [r["value"] for r in rows]
    assert "user-forever@example.com" in values
    assert "user-expired@example.com" not in values


def test_delete_suppression_deactivates(tmp_path):
    store = _store(tmp_path)
    row = store.create_suppression(suppression_type="entity_user", value="user@example.com")
    sid = row["id"]
    store.delete_suppression(sid)
    # Should no longer appear in active list
    active = store.list_suppressions()
    assert not any(r["id"] == sid for r in active)
    # But get_suppression still returns it (inactive)
    fetched = store.get_suppression(sid)
    assert fetched is not None
    assert fetched["active"] is False


def test_get_active_suppressions_returns_only_active(tmp_path):
    store = _store(tmp_path)
    s1 = store.create_suppression(suppression_type="alert_category", value="CredentialAccess")
    s2 = store.create_suppression(suppression_type="alert_title", value="ransomware")
    store.delete_suppression(s1["id"])
    active = store.get_active_suppressions()
    ids = [r["id"] for r in active]
    assert s1["id"] not in ids
    assert s2["id"] in ids
