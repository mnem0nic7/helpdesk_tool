from __future__ import annotations

from triage_store import TriageStore


def test_auto_triage_activity_backfill_seeds_changed_and_backfill_rows(tmp_path):
    store = TriageStore(str(tmp_path / "triage.db"))

    store.mark_auto_triaged("OIT-100")
    store.mark_auto_triaged("OIT-200")
    store.log_change(
        "OIT-100",
        "priority",
        "Medium",
        "High",
        0.97,
        "nemotron-3-nano:4b",
    )

    inserted = store.ensure_auto_triage_activity_backfill()

    assert inserted == 2
    activities = {
        entry["key"]: entry
        for entry in store.list_auto_triage_activity()
    }
    assert activities["OIT-100"]["outcome"] == "changed"
    assert activities["OIT-100"]["source"] == "migration"
    assert activities["OIT-100"]["model"] == "nemotron-3-nano:4b"
    assert activities["OIT-100"]["fields_changed"] == ["priority"]
    assert activities["OIT-100"]["legacy_backfill"] is False

    assert activities["OIT-200"]["outcome"] == "backfill"
    assert activities["OIT-200"]["source"] == "migration"
    assert activities["OIT-200"]["fields_changed"] == []
    assert activities["OIT-200"]["legacy_backfill"] is True


def test_clear_auto_triaged_keys_clears_activity_rows_too(tmp_path):
    store = TriageStore(str(tmp_path / "triage.db"))

    store.mark_auto_triaged("OIT-300")
    store.record_auto_triage_activity(
        "OIT-300",
        "changed",
        source="auto",
        model="nemotron-3-nano:4b",
        fields_changed=["priority"],
    )

    store.clear_auto_triaged_keys(["OIT-300"])

    assert store.get_auto_triaged_keys() == set()
    assert store.list_auto_triage_activity() == []
