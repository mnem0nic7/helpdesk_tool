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

def test_canonical_lane_order_matches_expected_sequence():
    from offboarding_runs import _LANE_ORDER

    assert _LANE_ORDER == [
        "entra_reset_pw",
        "entra_disable",
        "entra_revoke",
        "entra_reset_mfa",
        "entra_group_cleanup",
        "entra_group_validate",
        "mailbox_convert_shared",
        "entra_license_cleanup",
        "jira_deactivate",
        "ad_disable",
        "ad_reset_pw",
        "ad_group_cleanup",
        "ad_attribute_cleanup",
        "ad_move_ou",
    ]


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


def test_entra_group_cleanup_falls_back_to_exchange_for_distribution_lists():
    from offboarding_runs import run_offboarding

    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id="u1",
        ad_sam="",
        display_name="Jane",
        actor_email="admin@example.com",
        lanes=["entra_group_cleanup"],
    )

    mock_uap_module = MagicMock()
    mock_uap = MagicMock()
    mock_uap_module.user_admin_providers = mock_uap
    mock_uap.entra.remove_direct_cloud_group_memberships.return_value = {
        "summary": "Removed 1 direct cloud group membership(s)",
        "after_summary": {
            "removed_groups": ["GroupA"],
            "distribution_lists": [
                {"id": "dl-1", "name": "All Staff", "mail": "allstaff@example.com"}
            ],
        },
    }
    mock_uap.entra.client.graph_request.return_value = {"mail": "jane@example.com"}
    mock_uap.mailbox.exchange_powershell.remove_distribution_group_member.return_value = {
        "group": "allstaff@example.com",
        "member": "jane@example.com",
        "removed": True,
    }

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module, "ad_client": mock_ad}):
        run_offboarding(
            run_id="r1",
            entra_user_id="u1",
            ad_sam="",
            display_name="Jane",
            lanes=["entra_group_cleanup"],
            store=store,
        )

    mock_uap.mailbox.exchange_powershell.remove_distribution_group_member.assert_called_once_with(
        "allstaff@example.com", "jane@example.com"
    )
    run = store.get_run("r1")
    step = run["steps"][0]
    assert step["status"] == "ok"
    assert step["detail"]["distribution_lists_removed"] == ["All Staff"]
    assert run["has_errors"] is False


def test_entra_group_cleanup_records_failure_when_exchange_removal_fails():
    from offboarding_runs import run_offboarding

    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id="u1",
        ad_sam="",
        display_name="Jane",
        actor_email="admin@example.com",
        lanes=["entra_group_cleanup"],
    )

    mock_uap_module = MagicMock()
    mock_uap = MagicMock()
    mock_uap_module.user_admin_providers = mock_uap
    mock_uap.entra.remove_direct_cloud_group_memberships.return_value = {
        "summary": "Removed 0 direct cloud group membership(s)",
        "after_summary": {
            "removed_groups": [],
            "distribution_lists": [
                {"id": "dl-1", "name": "All Staff", "mail": "allstaff@example.com"}
            ],
        },
    }
    mock_uap.entra.client.graph_request.return_value = {"mail": "jane@example.com"}
    mock_uap.mailbox.exchange_powershell.remove_distribution_group_member.side_effect = RuntimeError("boom")

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module, "ad_client": mock_ad}):
        run_offboarding(
            run_id="r1",
            entra_user_id="u1",
            ad_sam="",
            display_name="Jane",
            lanes=["entra_group_cleanup"],
            store=store,
        )

    run = store.get_run("r1")
    step = run["steps"][0]
    assert step["status"] == "failed"
    assert "boom" in step["detail"]["distribution_list_failures"][0]
    assert run["has_errors"] is True


def test_mailbox_convert_shared_resolves_mail_and_converts():
    from offboarding_runs import run_offboarding

    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id="u1",
        ad_sam="",
        display_name="Jane",
        actor_email="admin@example.com",
        lanes=["mailbox_convert_shared"],
    )

    mock_uap_module = MagicMock()
    mock_uap = MagicMock()
    mock_uap_module.user_admin_providers = mock_uap
    mock_uap.entra.client.graph_request.return_value = {"mail": "jane@example.com"}
    mock_uap.mailbox.exchange_powershell.convert_mailbox_to_shared.return_value = {
        "mailbox": "jane@example.com",
        "recipient_type": "SharedMailbox",
        "hidden_from_address_lists": True,
    }

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module, "ad_client": mock_ad}):
        run_offboarding(
            run_id="r1",
            entra_user_id="u1",
            ad_sam="",
            display_name="Jane",
            lanes=["mailbox_convert_shared"],
            store=store,
        )

    mock_uap.mailbox.exchange_powershell.convert_mailbox_to_shared.assert_called_once_with("jane@example.com")
    run = store.get_run("r1")
    step = run["steps"][0]
    assert step["status"] == "ok"
    assert "SharedMailbox" in step["message"]


def _run_jira_lane(mock_jira_client: MagicMock, *, entra_user_id: str = "u1", display_name: str = "Jane") -> dict:
    """Run only the jira_deactivate lane with a mocked JiraClient; return the run dict."""
    from offboarding_runs import run_offboarding

    store = _fresh_store()
    store.create_run(
        run_id="r1",
        entra_user_id=entra_user_id,
        ad_sam="",
        display_name=display_name,
        actor_email="admin@example.com",
        lanes=["jira_deactivate"],
    )

    mock_uap_module = MagicMock()
    mock_uap = MagicMock()
    mock_uap_module.user_admin_providers = mock_uap
    mock_uap.entra.client.graph_request.return_value = {
        "mail": "jane@example.com",
        "userPrincipalName": "jane@example.com",
    }

    mock_jira_module = MagicMock()
    mock_jira_module.JiraClient.return_value = mock_jira_client

    with patch.dict(
        "sys.modules",
        {
            "user_admin_providers": mock_uap_module,
            "ad_client": MagicMock(),
            "jira_client": mock_jira_module,
        },
    ):
        run_offboarding(
            run_id="r1",
            entra_user_id=entra_user_id,
            ad_sam="",
            display_name=display_name,
            lanes=["jira_deactivate"],
            store=store,
        )
    return store.get_run("r1")


def test_jira_deactivate_lane_deactivates_account_found_by_email():
    jira = MagicMock()
    jira.find_user_by_email.return_value = {
        "accountId": "acc-123",
        "displayName": "Jane Doe",
        "active": True,
    }

    run = _run_jira_lane(jira)

    step = run["steps"][0]
    assert step["lane"] == "jira_deactivate"
    assert step["status"] == "ok"
    assert "deactivated" in step["message"].lower()
    assert step["detail"]["account_id"] == "acc-123"
    jira.find_user_by_email.assert_called_once_with("jane@example.com")
    jira.deactivate_user_account.assert_called_once()
    assert jira.deactivate_user_account.call_args.args[0] == "acc-123"
    assert run["has_errors"] is False


def test_jira_deactivate_lane_reports_no_account_without_failing():
    jira = MagicMock()
    jira.find_user_by_email.return_value = None
    jira.find_user_account_id.return_value = None

    run = _run_jira_lane(jira)

    step = run["steps"][0]
    assert step["status"] == "ok"
    assert "no jira account found" in step["message"].lower()
    assert step["detail"] == {"jira_account_found": False, "lookup_email": "jane@example.com"}
    jira.deactivate_user_account.assert_not_called()
    assert run["has_errors"] is False


def test_jira_deactivate_lane_skips_already_inactive_account():
    jira = MagicMock()
    jira.find_user_by_email.return_value = {
        "accountId": "acc-123",
        "displayName": "Jane Doe",
        "active": False,
    }

    run = _run_jira_lane(jira)

    step = run["steps"][0]
    assert step["status"] == "ok"
    assert "already deactivated" in step["message"].lower()
    jira.deactivate_user_account.assert_not_called()


def test_jira_deactivate_lane_falls_back_to_display_name_lookup():
    jira = MagicMock()
    jira.find_user_by_email.return_value = None
    jira.find_user_account_id.return_value = "acc-456"
    jira.get_user.return_value = {
        "accountId": "acc-456",
        "displayName": "Jane Doe",
        "active": True,
    }

    run = _run_jira_lane(jira)

    step = run["steps"][0]
    assert step["status"] == "ok"
    jira.find_user_account_id.assert_called_once_with("Jane")
    jira.deactivate_user_account.assert_called_once()
    assert jira.deactivate_user_account.call_args.args[0] == "acc-456"


def test_jira_deactivate_lane_records_failure_when_api_errors():
    jira = MagicMock()
    jira.find_user_by_email.return_value = {
        "accountId": "acc-123",
        "displayName": "Jane Doe",
        "active": True,
    }
    jira.deactivate_user_account.side_effect = RuntimeError(
        "ATLASSIAN_ADMIN_API_KEY is not configured; cannot deactivate Jira accounts"
    )

    run = _run_jira_lane(jira)

    step = run["steps"][0]
    assert step["status"] == "failed"
    assert "ATLASSIAN_ADMIN_API_KEY" in step["message"]
    assert run["has_errors"] is True


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
