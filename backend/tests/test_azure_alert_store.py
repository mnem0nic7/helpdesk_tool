from __future__ import annotations

import pytest
from azure_alert_store import AzureAlertStore

RULE = {
    "name": "Cost spike",
    "domain": "cost",
    "trigger_type": "cost_spike",
    "trigger_config": {"spike_pct": 20},
    "frequency": "daily",
    "recipients": "admin@example.com",
}


def test_create_and_get_rule(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    assert rule["id"]
    assert rule["name"] == "Cost spike"
    assert rule["enabled"] is True
    fetched = store.get_rule(rule["id"])
    assert fetched is not None
    assert fetched["domain"] == "cost"


def test_list_rules(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    store.create_rule(RULE)
    store.create_rule({**RULE, "name": "Rule 2"})
    assert len(store.list_rules()) == 2


def test_update_rule(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    updated = store.update_rule(rule["id"], {**RULE, "name": "Updated"})
    assert updated is not None
    assert updated["name"] == "Updated"


def test_toggle_rule(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    assert rule["enabled"] is True
    toggled = store.toggle_rule(rule["id"])
    assert toggled is not None
    assert toggled["enabled"] is False
    re_toggled = store.toggle_rule(rule["id"])
    assert re_toggled is not None
    assert re_toggled["enabled"] is True


def test_delete_rule_cascades_history(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    store.record_history(rule["id"], rule["name"], "cost_spike", "admin@x.com", 1, [], "sent", None)
    assert len(store.get_history()) == 1
    store.delete_rule(rule["id"])
    assert store.get_rule(rule["id"]) is None
    assert len(store.get_history()) == 0  # ON DELETE CASCADE


def test_update_last_run(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    assert store.get_rule(rule["id"])["last_run"] is None
    store.update_last_run(rule["id"])
    updated = store.get_rule(rule["id"])
    assert updated is not None
    assert updated["last_run"] is not None


def test_update_last_run_with_sent(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    store.update_last_run(rule["id"], last_sent=True)
    updated = store.get_rule(rule["id"])
    assert updated is not None
    assert updated["last_sent"] is not None


def test_get_history_filters_by_rule(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    r1 = store.create_rule(RULE)
    r2 = store.create_rule({**RULE, "name": "Rule 2"})
    store.record_history(r1["id"], r1["name"], "cost_spike", "a@x.com", 2, [], "sent", None)
    store.record_history(r2["id"], r2["name"], "cost_threshold", "b@x.com", 0, [], "sent", None)
    assert len(store.get_history(rule_id=r1["id"])) == 1
    assert len(store.get_history()) == 2


def test_vm_state_tracking(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    assert store.get_vm_first_seen_deallocated("vm-1") is None
    store.set_vm_first_seen_deallocated("vm-1", "2026-01-01T00:00:00+00:00")
    assert store.get_vm_first_seen_deallocated("vm-1") == "2026-01-01T00:00:00+00:00"
    # Second call is a no-op (INSERT OR IGNORE)
    store.set_vm_first_seen_deallocated("vm-1", "2026-02-01T00:00:00+00:00")
    assert store.get_vm_first_seen_deallocated("vm-1") == "2026-01-01T00:00:00+00:00"


def test_purge_vm_states(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    store.set_vm_first_seen_deallocated("vm-1", "2026-01-01T00:00:00+00:00")
    store.set_vm_first_seen_deallocated("vm-2", "2026-01-01T00:00:00+00:00")
    store.purge_vm_states({"vm-1"})  # vm-2 no longer deallocated
    assert store.get_vm_first_seen_deallocated("vm-1") is not None
    assert store.get_vm_first_seen_deallocated("vm-2") is None


def test_user_state_tracking(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    assert store.get_user_state("u-1") is None
    store.upsert_user_state("u-1", True)
    state = store.get_user_state("u-1")
    assert state is not None
    assert state["enabled"] is True
    store.upsert_user_state("u-1", False)
    state = store.get_user_state("u-1")
    assert state is not None
    assert state["enabled"] is False
