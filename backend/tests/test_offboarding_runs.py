"""Tests for the offboarding_runs orchestrator, store, and CSV renderer."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Store: SQLite round-trip
# ---------------------------------------------------------------------------

def _fresh_store():
    from offboarding_runs import OffboardingRunsStore
    tmp = tempfile.mktemp(suffix=".db")
    return OffboardingRunsStore(db_path=tmp)


def test_create_and_get_run_round_trips():
    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id="u1",
        ad_sam="jdoe",
        display_name="Jane Doe",
        actor_email="admin@example.com",
        lanes=["entra_disable", "ad_disable"],
    )
    run = store.get_run("r1")

    assert run is not None
    assert run["run_id"] == "r1"
    assert run["status"] == "queued"
    assert run["lanes_requested"] == ["entra_disable", "ad_disable"]
    assert run["has_errors"] is False
    assert run["steps"] == []


def test_start_run_updates_status_to_running():
    store = _fresh_store()
    store.create_run(run_id="r1", entra_user_id="u1", ad_sam="", display_name="", actor_email="", lanes=[])
    store.start_run("r1")
    run = store.get_run("r1")

    assert run["status"] == "running"
    assert run["started_at"] is not None


def test_finish_run_sets_completed_status():
    store = _fresh_store()
    store.create_run(run_id="r1", entra_user_id="u1", ad_sam="", display_name="", actor_email="", lanes=[])
    store.finish_run("r1", has_errors=False)
    run = store.get_run("r1")

    assert run["status"] == "completed"
    assert run["has_errors"] is False


def test_finish_run_sets_completed_with_errors():
    store = _fresh_store()
    store.create_run(run_id="r1", entra_user_id="u1", ad_sam="", display_name="", actor_email="", lanes=[])
    store.finish_run("r1", has_errors=True)
    run = store.get_run("r1")

    assert run["status"] == "completed_with_errors"
    assert run["has_errors"] is True


def test_append_and_update_step_round_trips():
    store = _fresh_store()
    store.create_run(run_id="r1", entra_user_id="u1", ad_sam="", display_name="", actor_email="", lanes=[])
    step_id = store.append_step(run_id="r1", lane="entra_disable", sequence=0)
    store.update_step(
        step_id=step_id,
        status="ok",
        message="Disabled sign-in",
        detail={"enabled": False},
        started_at="2026-04-01T00:00:01+00:00",
        finished_at="2026-04-01T00:00:02+00:00",
    )
    run = store.get_run("r1")

    assert len(run["steps"]) == 1
    step = run["steps"][0]
    assert step["step_id"] == step_id
    assert step["lane"] == "entra_disable"
    assert step["status"] == "ok"
    assert step["message"] == "Disabled sign-in"
    assert step["detail"] == {"enabled": False}


def test_get_run_returns_none_for_missing():
    store = _fresh_store()
    assert store.get_run("nonexistent") is None


def test_list_runs_returns_ordered_descending():
    store = _fresh_store()
    store.create_run(run_id="r1", entra_user_id="u1", ad_sam="", display_name="Alice", actor_email="", lanes=[])
    store.create_run(run_id="r2", entra_user_id="u2", ad_sam="", display_name="Bob", actor_email="", lanes=[])
    runs = store.list_runs(limit=10)

    # Both present; r2 was created after r1 so should appear first
    assert len(runs) == 2
    assert runs[0]["run_id"] in ("r1", "r2")


# ---------------------------------------------------------------------------
# Store: CSV renderer
# ---------------------------------------------------------------------------

def test_render_csv_contains_expected_columns():
    store = _fresh_store()
    store.create_run(run_id="r1", entra_user_id="u1", ad_sam="", display_name="Jane Doe", actor_email="", lanes=["entra_disable"])
    step_id = store.append_step(run_id="r1", lane="entra_disable", sequence=0)
    store.update_step(
        step_id=step_id,
        status="ok",
        message="Disabled",
        detail=None,
        started_at="2026-04-01T00:00:01+00:00",
        finished_at="2026-04-01T00:00:02+00:00",
    )

    csv_content = store.render_csv("r1")

    assert "run_id" in csv_content
    assert "display_name" in csv_content
    assert "lane" in csv_content
    assert "status" in csv_content
    assert "Jane Doe" in csv_content
    assert "entra_disable" in csv_content
    assert "ok" in csv_content


def test_render_csv_returns_empty_for_missing_run():
    store = _fresh_store()
    assert store.render_csv("nonexistent") == ""


# ---------------------------------------------------------------------------
# Orchestrator: lane ordering and step creation
# ---------------------------------------------------------------------------

def test_run_offboarding_executes_lanes_in_canonical_order():
    from offboarding_runs import run_offboarding

    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id="u1",
        ad_sam="jdoe",
        display_name="Jane",
        actor_email="admin@example.com",
        lanes=["ad_disable", "entra_disable"],  # reversed from canonical order
    )

    mock_uap_module = MagicMock()
    mock_uap = MagicMock()
    mock_uap_module.user_admin_providers = mock_uap
    mock_uap.entra.execute.return_value = {"summary": "ok"}
    mock_uap.entra.remove_direct_cloud_group_memberships.return_value = {
        "summary": "ok", "after_summary": {"removed_groups": []}
    }
    mock_uap.entra.validate_cloud_group_removal.return_value = {"ok": True, "still_present_count": 0}
    mock_uap.entra.remove_all_direct_licenses.return_value = {"summary": "ok"}

    mock_ad = MagicMock()
    mock_ad.disable_user.return_value = None

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module, "ad_client": mock_ad}):
        run_offboarding(
            run_id="r1",
            entra_user_id="u1",
            ad_sam="jdoe",
            display_name="Jane",
            lanes=["ad_disable", "entra_disable"],
            store=store,
        )

    run = store.get_run("r1")
    assert run["status"] in ("completed", "completed_with_errors")
    sequences = [s["sequence"] for s in run["steps"]]
    # entra_disable (index 0) should appear before ad_disable (index 6) in canonical order
    lanes_in_order = [s["lane"] for s in sorted(run["steps"], key=lambda s: s["sequence"])]
    assert lanes_in_order.index("entra_disable") < lanes_in_order.index("ad_disable")


def test_run_offboarding_records_failed_step_and_continues():
    from offboarding_runs import run_offboarding

    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id="u1",
        ad_sam="jdoe",
        display_name="Jane",
        actor_email="admin@example.com",
        lanes=["entra_disable", "entra_revoke"],
    )

    mock_uap_module = MagicMock()
    mock_uap = MagicMock()
    mock_uap_module.user_admin_providers = mock_uap
    mock_uap.entra.execute.side_effect = [
        Exception("Graph error"),  # entra_disable fails
        {"summary": "Sessions revoked"},  # entra_revoke succeeds
    ]

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module, "ad_client": mock_ad}):
        run_offboarding(
            run_id="r1",
            entra_user_id="u1",
            ad_sam="jdoe",
            display_name="Jane",
            lanes=["entra_disable", "entra_revoke"],
            store=store,
        )

    run = store.get_run("r1")
    step_statuses = {s["lane"]: s["status"] for s in run["steps"]}

    assert step_statuses["entra_disable"] == "failed"
    assert step_statuses["entra_revoke"] == "ok"
    assert run["status"] == "completed_with_errors"
    assert run["has_errors"] is True


def test_run_offboarding_passes_removed_groups_to_validate_lane():
    from offboarding_runs import run_offboarding

    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id="u1",
        ad_sam="",
        display_name="Jane",
        actor_email="admin@example.com",
        lanes=["entra_group_cleanup", "entra_group_validate"],
    )

    removed_groups = ["GroupA", "GroupB"]

    mock_uap_module = MagicMock()
    mock_uap = MagicMock()
    mock_uap_module.user_admin_providers = mock_uap
    mock_uap.entra.remove_direct_cloud_group_memberships.return_value = {
        "summary": "Removed 2 groups",
        "after_summary": {"removed_groups": removed_groups},
    }
    validate_calls: list[list] = []

    def fake_validate(user_id: str, groups: list[str]) -> dict:
        validate_calls.append(groups)
        return {"ok": True, "still_present_count": 0}

    mock_uap.entra.validate_cloud_group_removal.side_effect = fake_validate

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module, "ad_client": mock_ad}):
        run_offboarding(
            run_id="r1",
            entra_user_id="u1",
            ad_sam="",
            display_name="Jane",
            lanes=["entra_group_cleanup", "entra_group_validate"],
            store=store,
        )

    assert validate_calls == [removed_groups]


def test_run_offboarding_marks_validate_lane_failed_when_groups_remain():
    from offboarding_runs import run_offboarding

    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id="u1",
        ad_sam="",
        display_name="Jane",
        actor_email="admin@example.com",
        lanes=["entra_group_cleanup", "entra_group_validate"],
    )

    mock_uap_module = MagicMock()
    mock_uap = MagicMock()
    mock_uap_module.user_admin_providers = mock_uap
    mock_uap.entra.remove_direct_cloud_group_memberships.return_value = {
        "summary": "Removed 1 group",
        "after_summary": {"removed_groups": ["GroupA"]},
    }
    mock_uap.entra.validate_cloud_group_removal.return_value = {
        "ok": False,
        "still_present_count": 1,
        "remaining_groups": ["GroupA"],
    }

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module, "ad_client": mock_ad}):
        run_offboarding(
            run_id="r1",
            entra_user_id="u1",
            ad_sam="",
            display_name="Jane",
            lanes=["entra_group_cleanup", "entra_group_validate"],
            store=store,
        )

    run = store.get_run("r1")
    validate_step = next(s for s in run["steps"] if s["lane"] == "entra_group_validate")
    assert validate_step["status"] == "failed"
    assert run["has_errors"] is True
