from __future__ import annotations

from security_finding_exception_store import SecurityFindingExceptionStore


def test_security_finding_exception_store_round_trips_active_exceptions(tmp_path):
    store = SecurityFindingExceptionStore(db_path=str(tmp_path / "security_finding_exceptions.db"))

    created = store.upsert_exception(
        scope="directory_user",
        entity_id="user-1",
        entity_label="Guest Vendor",
        entity_subtitle="guest.vendor@example.com",
        reason="Approved long-lived vendor guest account.",
        actor_email="reviewer@example.com",
        actor_name="Review User",
    )

    assert created["status"] == "active"
    assert created["entity_id"] == "user-1"

    active = store.list_exceptions(scope="directory_user")
    assert len(active) == 1
    assert active[0]["reason"] == "Approved long-lived vendor guest account."
    assert store.get_active_entity_ids("directory_user") == {"user-1"}


def test_security_finding_exception_store_restores_and_reactivates_exception(tmp_path):
    store = SecurityFindingExceptionStore(db_path=str(tmp_path / "security_finding_exceptions.db"))

    created = store.upsert_exception(
        scope="directory_user",
        entity_id="user-1",
        entity_label="Guest Vendor",
        reason="Approved long-lived vendor guest account.",
        actor_email="reviewer@example.com",
        actor_name="Review User",
    )

    restored = store.restore_exception(
        created["exception_id"],
        actor_email="reviewer@example.com",
        actor_name="Review User",
    )

    assert restored is not None
    assert restored["status"] == "restored"
    assert store.get_active_entity_ids("directory_user") == set()

    reactivated = store.upsert_exception(
        scope="directory_user",
        entity_id="user-1",
        entity_label="Guest Vendor",
        reason="Re-approved vendor guest account.",
        actor_email="reviewer@example.com",
        actor_name="Review User",
    )

    assert reactivated["exception_id"] == created["exception_id"]
    assert reactivated["status"] == "active"
    assert reactivated["reason"] == "Re-approved vendor guest account."
    assert store.get_active_entity_ids("directory_user") == {"user-1"}
