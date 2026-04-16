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
    assert dec["mitre_techniques"] == []


def test_create_decision_with_mitre_techniques(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-mitre",
        run_id="run-1",
        alert_id="ext-mitre-1",
        alert_title="Suspicious Sign-In",
        alert_severity="high",
        alert_category="CredentialAccess",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForIdentity",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="Test",
        entities=[],
        mitre_techniques=["T1078", "T1110.003"],
    )
    dec = store.get_decision("dec-mitre")
    assert dec is not None
    assert "T1078" in dec["mitre_techniques"]
    assert "T1110.003" in dec["mitre_techniques"]


def test_decision_mitre_techniques_default_empty(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store)
    dec = store.get_decision("dec-1")
    assert isinstance(dec["mitre_techniques"], list)
    assert dec["mitre_techniques"] == []


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


# ---------------------------------------------------------------------------
# Phase 7 — entity_cooldown_hours config + get_recent_entity_actions
# ---------------------------------------------------------------------------

def test_default_config_includes_entity_cooldown_hours(tmp_path):
    store = _store(tmp_path)
    cfg = store.get_config()
    assert "entity_cooldown_hours" in cfg
    assert cfg["entity_cooldown_hours"] == 24


def test_upsert_config_entity_cooldown_hours(tmp_path):
    store = _store(tmp_path)
    defaults = store.get_config()
    store.upsert_config(
        enabled=defaults["enabled"],
        min_severity=defaults["min_severity"],
        tier2_delay_minutes=defaults["tier2_delay_minutes"],
        dry_run=defaults["dry_run"],
        entity_cooldown_hours=48,
    )
    cfg = store.get_config()
    assert cfg["entity_cooldown_hours"] == 48


def test_upsert_config_cooldown_zero_allowed(tmp_path):
    store = _store(tmp_path)
    defaults = store.get_config()
    store.upsert_config(
        enabled=defaults["enabled"],
        min_severity=defaults["min_severity"],
        tier2_delay_minutes=defaults["tier2_delay_minutes"],
        dry_run=defaults["dry_run"],
        entity_cooldown_hours=0,
    )
    cfg = store.get_config()
    assert cfg["entity_cooldown_hours"] == 0


def test_get_recent_entity_actions_empty(tmp_path):
    store = _store(tmp_path)
    result = store.get_recent_entity_actions(hours=24)
    assert result == {}


def test_get_recent_entity_actions_zero_hours_returns_empty(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-zh", action_type="revoke_sessions")
    store.update_decision_jobs(row["decision_id"], ["job-zh"])
    result = store.get_recent_entity_actions(hours=0)
    assert result == {}


def test_get_recent_entity_actions_returns_dispatched(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-rd", action_type="revoke_sessions")
    store.update_decision_jobs(row["decision_id"], ["job-001"])
    result = store.get_recent_entity_actions(hours=24)
    assert "user-1" in result
    assert "revoke_sessions" in result["user-1"]


def test_get_recent_entity_actions_skips_not_dispatched(tmp_path):
    store = _store(tmp_path)
    _make_decision(store, decision_id="dec-nd", decision="skip", action_type="revoke_sessions")
    result = store.get_recent_entity_actions(hours=24)
    assert "user-1" not in result


def test_get_recent_entity_actions_multi_entity(tmp_path):
    store = _store(tmp_path)
    row = store.create_decision(
        decision_id="dec-me",
        run_id="run-me",
        alert_id="a2",
        alert_title="Multi",
        alert_severity="medium",
        alert_category="Malware",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForEndpoint",
        tier=1,
        decision="execute",
        action_type="isolate_device",
        action_types=["isolate_device"],
        job_ids=[],
        reason="test",
        entities=[
            {"type": "user", "id": "u1", "name": "Alice"},
            {"type": "device", "id": "dev1", "name": "WS-01"},
        ],
    )
    store.update_decision_jobs(row["decision_id"], ["job-002"])
    result = store.get_recent_entity_actions(hours=24)
    assert "u1" in result or "dev1" in result


# ---------------------------------------------------------------------------
# Phase 8 — alert_dedup_window_minutes config + get_recent_decisions_for_dedup
# ---------------------------------------------------------------------------

def test_default_config_includes_alert_dedup_window_minutes(tmp_path):
    store = _store(tmp_path)
    cfg = store.get_config()
    assert "alert_dedup_window_minutes" in cfg
    assert cfg["alert_dedup_window_minutes"] == 30


def test_upsert_config_alert_dedup_window_minutes(tmp_path):
    store = _store(tmp_path)
    defaults = store.get_config()
    store.upsert_config(
        enabled=defaults["enabled"],
        min_severity=defaults["min_severity"],
        tier2_delay_minutes=defaults["tier2_delay_minutes"],
        dry_run=defaults["dry_run"],
        alert_dedup_window_minutes=60,
    )
    cfg = store.get_config()
    assert cfg["alert_dedup_window_minutes"] == 60


def test_upsert_config_alert_dedup_window_zero(tmp_path):
    store = _store(tmp_path)
    defaults = store.get_config()
    store.upsert_config(
        enabled=defaults["enabled"],
        min_severity=defaults["min_severity"],
        tier2_delay_minutes=defaults["tier2_delay_minutes"],
        dry_run=defaults["dry_run"],
        alert_dedup_window_minutes=0,
    )
    cfg = store.get_config()
    assert cfg["alert_dedup_window_minutes"] == 0


def test_get_recent_decisions_for_dedup_empty(tmp_path):
    store = _store(tmp_path)
    result = store.get_recent_decisions_for_dedup(since_minutes=30)
    assert result == []


def test_get_recent_decisions_for_dedup_zero_minutes_returns_empty(tmp_path):
    store = _store(tmp_path)
    _make_decision(store, decision_id="dec-dm0")
    result = store.get_recent_decisions_for_dedup(since_minutes=0)
    assert result == []


def test_get_recent_decisions_for_dedup_returns_non_skip(tmp_path):
    store = _store(tmp_path)
    _make_decision(store, decision_id="dec-act", decision="execute", action_type="revoke_sessions")
    result = store.get_recent_decisions_for_dedup(since_minutes=30)
    assert len(result) == 1
    assert result[0]["decision_id"] == "dec-act"
    assert "revoke_sessions" in result[0]["action_types"]


def test_get_recent_decisions_for_dedup_excludes_skip(tmp_path):
    store = _store(tmp_path)
    _make_decision(store, decision_id="dec-skip", decision="skip")
    result = store.get_recent_decisions_for_dedup(since_minutes=30)
    assert result == []


def test_get_recent_decisions_for_dedup_excludes_cancelled(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-can", decision="queue")
    store.cancel_decision(row["decision_id"], cancelled_by="admin@example.com")
    result = store.get_recent_decisions_for_dedup(since_minutes=30)
    assert all(r["decision_id"] != "dec-can" for r in result)


def test_get_recent_decisions_for_dedup_includes_entities(tmp_path):
    store = _store(tmp_path)
    _make_decision(store, decision_id="dec-ent", action_type="revoke_sessions")
    result = store.get_recent_decisions_for_dedup(since_minutes=30)
    assert len(result) == 1
    assert any(e.get("type") == "user" for e in result[0]["entities"])


# ---------------------------------------------------------------------------
# Phase 9 — remediation confirmation
# ---------------------------------------------------------------------------

def test_get_unconfirmed_actioned_decisions_empty(tmp_path):
    store = _store(tmp_path)
    assert store.get_unconfirmed_actioned_decisions() == []


def test_get_unconfirmed_actioned_decisions_no_jobs(tmp_path):
    store = _store(tmp_path)
    _make_decision(store, decision_id="dec-nj")
    # No job_ids — should NOT appear
    result = store.get_unconfirmed_actioned_decisions()
    assert result == []


def test_get_unconfirmed_actioned_decisions_with_jobs(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-wj")
    store.update_decision_jobs(row["decision_id"], ["job-001"])
    result = store.get_unconfirmed_actioned_decisions()
    assert len(result) == 1
    assert result[0]["decision_id"] == "dec-wj"
    assert "job-001" in result[0]["job_ids"]


def test_get_unconfirmed_actioned_decisions_excludes_skip(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-sk", decision="skip")
    store.update_decision_jobs(row["decision_id"], ["job-sk1"])
    result = store.get_unconfirmed_actioned_decisions()
    assert result == []


def test_update_decision_remediation_confirmed(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-rc")
    store.update_decision_jobs(row["decision_id"], ["job-x"])
    store.update_decision_remediation(row["decision_id"], confirmed=True, failed=False)
    fetched = store.get_decision(row["decision_id"])
    assert fetched["remediation_confirmed"] is True
    assert fetched["remediation_failed"] is False
    assert fetched["confirmed_at"] is not None


def test_update_decision_remediation_failed(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-rf")
    store.update_decision_jobs(row["decision_id"], ["job-y"])
    store.update_decision_remediation(row["decision_id"], confirmed=False, failed=True)
    fetched = store.get_decision(row["decision_id"])
    assert fetched["remediation_confirmed"] is False
    assert fetched["remediation_failed"] is True
    assert fetched["confirmed_at"] is not None


def test_get_unconfirmed_excludes_already_confirmed(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-ac")
    store.update_decision_jobs(row["decision_id"], ["job-z"])
    store.update_decision_remediation(row["decision_id"], confirmed=True, failed=False)
    result = store.get_unconfirmed_actioned_decisions()
    assert all(r["decision_id"] != "dec-ac" for r in result)


def test_decision_remediation_defaults_false(tmp_path):
    store = _store(tmp_path)
    row = _make_decision(store, decision_id="dec-def")
    fetched = store.get_decision(row["decision_id"])
    assert fetched["remediation_confirmed"] is False
    assert fetched["remediation_failed"] is False
    assert fetched.get("confirmed_at") is None


# ---------------------------------------------------------------------------
# Phase 10 — Confidence scoring store tests
# ---------------------------------------------------------------------------


def test_config_min_confidence_default(tmp_path):
    store = _store(tmp_path)
    cfg = store.get_config()
    assert "min_confidence" in cfg
    assert cfg["min_confidence"] == 0


def test_upsert_config_min_confidence(tmp_path):
    store = _store(tmp_path)
    store.upsert_config(enabled=True, min_severity="high", tier2_delay_minutes=15,
                        dry_run=False, min_confidence=75)
    cfg = store.get_config()
    assert cfg["min_confidence"] == 75


def test_create_decision_stores_confidence_score(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-conf",
        run_id="run-1",
        alert_id="alert-c",
        alert_title="Test",
        alert_severity="high",
        alert_category="Malware",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForEndpoint",
        entities=[],
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        job_ids=[],
        reason="Test",
        confidence_score=82,
    )
    dec = store.get_decision("dec-conf")
    assert dec is not None
    assert dec["confidence_score"] == 82


def test_create_decision_defaults_confidence_zero(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision_id="dec-noconf")
    dec = store.get_decision("dec-noconf")
    assert dec is not None
    assert dec["confidence_score"] == 0


def test_list_decisions_includes_confidence_score(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-listconf",
        run_id="run-1",
        alert_id="alert-lc",
        alert_title="Test",
        alert_severity="high",
        alert_category="Malware",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForEndpoint",
        entities=[],
        tier=2,
        decision="queue",
        action_type="disable_sign_in",
        job_ids=[],
        reason="Test",
        confidence_score=68,
    )
    decisions, total = store.list_decisions()
    match = next((d for d in decisions if d["decision_id"] == "dec-listconf"), None)
    assert match is not None
    assert match["confidence_score"] == 68


# ---------------------------------------------------------------------------
# Phase 12 — Analyst disposition
# ---------------------------------------------------------------------------


def test_set_decision_disposition_true_positive(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    row = _make_decision(store, decision_id="dec-tp")
    result = store.set_decision_disposition(row["decision_id"], "true_positive", by="analyst@example.com")
    assert result is not None
    assert result["disposition"] == "true_positive"
    assert result["disposition_by"] == "analyst@example.com"
    assert result["disposition_at"] is not None


def test_set_decision_disposition_false_positive(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    row = _make_decision(store, decision_id="dec-fp")
    result = store.set_decision_disposition(row["decision_id"], "false_positive", note="Noise from lab machine")
    assert result is not None
    assert result["disposition"] == "false_positive"
    assert result["disposition_note"] == "Noise from lab machine"


def test_set_decision_disposition_inconclusive(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    row = _make_decision(store, decision_id="dec-inc")
    result = store.set_decision_disposition(row["decision_id"], "inconclusive")
    assert result is not None
    assert result["disposition"] == "inconclusive"


def test_set_decision_disposition_invalid_raises(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    row = _make_decision(store, decision_id="dec-invalid")
    import pytest
    with pytest.raises(ValueError):
        store.set_decision_disposition(row["decision_id"], "banana")


def test_set_decision_disposition_not_found_returns_none(tmp_path):
    store = _store(tmp_path)
    result = store.set_decision_disposition("nonexistent", "true_positive")
    assert result is None


def test_decision_disposition_defaults_null(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    row = _make_decision(store, decision_id="dec-nodisp")
    fetched = store.get_decision(row["decision_id"])
    assert fetched["disposition"] is None
    assert fetched["disposition_note"] == ""
    assert fetched["disposition_by"] == ""
    assert fetched["disposition_at"] is None


def test_get_disposition_stats_empty(tmp_path):
    store = _store(tmp_path)
    stats = store.get_disposition_stats()
    assert stats["total_actioned"] == 0
    assert stats["reviewed"] == 0
    assert stats["false_positive_rate"] == 0.0


def test_get_disposition_stats_counts(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    for i, (dec_id, decision, disp) in enumerate([
        ("dec-s1", "execute", "true_positive"),
        ("dec-s2", "execute", "false_positive"),
        ("dec-s3", "queue",   "true_positive"),
        ("dec-s4", "recommend", None),
        ("dec-s5", "skip",    None),  # skips excluded
    ]):
        _make_decision(store, decision_id=dec_id, decision=decision)
        if disp:
            store.set_decision_disposition(dec_id, disp)
    stats = store.get_disposition_stats()
    # 4 non-skip decisions; 3 reviewed
    assert stats["total_actioned"] == 4
    assert stats["reviewed"] == 3
    assert stats["unreviewed"] == 1
    assert stats["true_positive"] == 2
    assert stats["false_positive"] == 1
    assert stats["inconclusive"] == 0
    assert round(stats["false_positive_rate"], 3) == round(1 / 3, 3)


def test_disposition_stats_fp_rate_all_tp(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    for i in range(3):
        row = _make_decision(store, decision_id=f"dec-alltp-{i}")
        store.set_decision_disposition(row["decision_id"], "true_positive")
    stats = store.get_disposition_stats()
    assert stats["false_positive_rate"] == 0.0
    assert stats["true_positive"] == 3


# ---------------------------------------------------------------------------
# Phase 13: Entity timeline
# ---------------------------------------------------------------------------

def test_entity_timeline_empty(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    result = store.get_entity_timeline("nobody@example.com")
    assert result == []


def test_entity_timeline_matches_by_id(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-ent-1",
        run_id="run-1",
        alert_id="a1",
        alert_title="Test",
        alert_severity="high",
        alert_category="Suspicious",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="mde",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="r",
        entities=[{"type": "user", "id": "user-abc", "name": "alice@example.com"}],
        not_before_at=None,
    )
    result = store.get_entity_timeline("user-abc")
    assert len(result) == 1
    assert result[0]["decision_id"] == "dec-ent-1"


def test_entity_timeline_matches_by_name(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-ent-2",
        run_id="run-1",
        alert_id="a2",
        alert_title="Test2",
        alert_severity="medium",
        alert_category="Suspicious",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="mde",
        tier=2,
        decision="queue",
        action_type="disable_sign_in",
        action_types=["disable_sign_in"],
        job_ids=[],
        reason="r",
        entities=[{"type": "user", "id": "user-xyz", "name": "bob@example.com"}],
        not_before_at=None,
    )
    result = store.get_entity_timeline("bob@example.com")
    assert len(result) == 1
    assert result[0]["decision_id"] == "dec-ent-2"


def test_entity_timeline_no_false_positive_substring_match(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-ent-3",
        run_id="run-1",
        alert_id="a3",
        alert_title="Test3",
        alert_severity="low",
        alert_category="Suspicious",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="mde",
        tier=3,
        decision="recommend",
        action_type="device_wipe",
        action_types=["device_wipe"],
        job_ids=[],
        reason="r",
        entities=[{"type": "device", "id": "device-longname-extra", "name": "LAPTOP001-extra"}],
        not_before_at=None,
    )
    # Substring of name — should NOT match (exact matching only)
    result = store.get_entity_timeline("LAPTOP001")
    assert result == []
    # Exact match by name — should match
    result_exact = store.get_entity_timeline("LAPTOP001-extra")
    assert len(result_exact) == 1


def test_entity_timeline_multiple_decisions(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    for i in range(3):
        store.create_decision(
            decision_id=f"dec-multi-{i}",
            run_id="run-1",
            alert_id=f"alert-multi-{i}",
            alert_title=f"Alert {i}",
            alert_severity="high",
            alert_category="Suspicious",
            alert_created_at="2026-04-16T00:00:00Z",
            service_source="mde",
            tier=1,
            decision="execute",
            action_type="revoke_sessions",
            action_types=["revoke_sessions"],
            job_ids=[],
            reason="r",
            entities=[{"type": "user", "id": "shared-user", "name": "shared@example.com"}],
            not_before_at=None,
        )
    result = store.get_entity_timeline("shared-user")
    assert len(result) == 3


def test_entity_timeline_limit(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    for i in range(10):
        store.create_decision(
            decision_id=f"dec-lim-{i}",
            run_id="run-1",
            alert_id=f"alert-lim-{i}",
            alert_title=f"Alert {i}",
            alert_severity="medium",
            alert_category="Suspicious",
            alert_created_at="2026-04-16T00:00:00Z",
            service_source="mde",
            tier=1,
            decision="execute",
            action_type="revoke_sessions",
            action_types=["revoke_sessions"],
            job_ids=[],
            reason="r",
            entities=[{"type": "user", "id": "lim-user", "name": "lim@example.com"}],
            not_before_at=None,
        )
    result = store.get_entity_timeline("lim-user", limit=5)
    assert len(result) == 5


# ---------------------------------------------------------------------------
# Phase 14: Agent metrics
# ---------------------------------------------------------------------------

def test_get_agent_metrics_empty(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    m = store.get_agent_metrics(days=30)
    assert m["total_decisions"] == 0
    assert m["by_tier"] == {"T1": 0, "T2": 0, "T3": 0, "skip": 0}
    assert m["daily_volumes"] == []
    assert m["top_entities"] == []
    assert m["top_alert_titles"] == []
    assert m["false_positive_rate"] == 0.0
    assert m["top_actions"] == []


def test_get_agent_metrics_tier_counts(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision_id="dec-m1", decision="execute", tier=1)
    _make_decision(store, decision_id="dec-m2", decision="queue", tier=2)
    _make_decision(store, decision_id="dec-m3", decision="queue", tier=2)
    _make_decision(store, decision_id="dec-m4", decision="recommend", tier=3)
    _make_decision(store, decision_id="dec-m5", decision="skip", tier=None)
    m = store.get_agent_metrics(days=30)
    assert m["total_decisions"] == 5
    assert m["by_tier"]["T1"] == 1
    assert m["by_tier"]["T2"] == 2
    assert m["by_tier"]["T3"] == 1
    assert m["by_tier"]["skip"] == 1


def test_get_agent_metrics_daily_volumes(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision_id="dec-mv1")
    _make_decision(store, decision_id="dec-mv2")
    m = store.get_agent_metrics(days=30)
    assert len(m["daily_volumes"]) == 1
    assert m["daily_volumes"][0]["count"] == 2


def test_get_agent_metrics_top_entities(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    for i in range(3):
        store.create_decision(
            decision_id=f"dec-me-{i}",
            run_id="run-1",
            alert_id=f"a-{i}",
            alert_title="Test",
            alert_severity="high",
            alert_category="Suspicious",
            alert_created_at="2026-04-16T00:00:00Z",
            service_source="mde",
            tier=1,
            decision="execute",
            action_type="revoke_sessions",
            action_types=["revoke_sessions"],
            job_ids=[],
            reason="r",
            entities=[{"type": "user", "id": "top-user", "name": "top@example.com"}],
            not_before_at=None,
        )
    m = store.get_agent_metrics(days=30)
    assert len(m["top_entities"]) == 1
    assert m["top_entities"][0]["id"] == "top-user"
    assert m["top_entities"][0]["count"] == 3


def test_get_agent_metrics_disposition_and_fp_rate(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    for i in range(4):
        row = _make_decision(store, decision_id=f"dec-mfp-{i}")
    store.set_decision_disposition("dec-mfp-0", "true_positive")
    store.set_decision_disposition("dec-mfp-1", "false_positive")
    store.set_decision_disposition("dec-mfp-2", "inconclusive")
    m = store.get_agent_metrics(days=30)
    ds = m["disposition_summary"]
    assert ds["true_positive"] == 1
    assert ds["false_positive"] == 1
    assert ds["inconclusive"] == 1
    assert ds["unreviewed"] == 1
    assert round(m["false_positive_rate"], 3) == round(1 / 3, 3)


def test_get_agent_metrics_period_days_filter(tmp_path):
    store = _store(tmp_path)
    store.create_run("run-1")
    _make_decision(store, decision_id="dec-old")
    # With 0-day window nothing should show (executed_at is just now, so 1-day should include)
    m_1 = store.get_agent_metrics(days=1)
    m_90 = store.get_agent_metrics(days=90)
    assert m_1["total_decisions"] == m_90["total_decisions"]
    assert m_1["period_days"] == 1
    assert m_90["period_days"] == 90
