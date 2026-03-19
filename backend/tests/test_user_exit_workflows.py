from __future__ import annotations

import sqlite3

from user_exit_workflows import UserExitWorkflowManager


def test_build_preflight_requires_override_for_mapped_synced_user(tmp_path, monkeypatch):
    manager = UserExitWorkflowManager(db_path=str(tmp_path / "user_exit_workflows.db"))

    class FakeProviders:
        @staticmethod
        def get_user_detail(user_id):
            assert user_id == "user-1"
            return {
                "id": "user-1",
                "display_name": "Taylor Exit",
                "principal_name": "taylor@canyon.example",
                "mail": "taylor@canyon.example",
                "job_title": "Business Development Executive",
                "on_prem_sync": True,
                "on_prem_domain": "canyon.local",
                "on_prem_netbios": "CANYON",
                "on_prem_sam_account_name": "",
                "on_prem_distinguished_name": "",
            }

        @staticmethod
        def list_licenses(user_id):
            assert user_id == "user-1"
            return [{"sku_id": "sku-1", "sku_part_number": "M365_BUSINESS_PREMIUM", "display_name": "Business Premium"}]

        @staticmethod
        def list_devices(user_id):
            assert user_id == "user-1"
            return [{"id": "device-1", "device_name": "LAPTOP-01"}]

        @staticmethod
        def get_mailbox(user_id):
            assert user_id == "user-1"
            return {"primary_address": "taylor@canyon.example"}

    monkeypatch.setattr("user_exit_workflows.user_admin_providers", FakeProviders())

    preflight = manager.build_preflight("user-1")

    assert preflight["profile_key"] == "canyon"
    assert preflight["on_prem_required"] is True
    assert preflight["requires_on_prem_username_override"] is True
    assert any(step["step_key"] == "exit_on_prem_deprovision" and step["will_run"] is False for step in preflight["steps"])
    assert "Salesforce deactivation email" in [task["label"] for task in preflight["manual_tasks"]]


def test_workflow_processes_local_steps_and_completes_after_manual_tasks(tmp_path, monkeypatch):
    manager = UserExitWorkflowManager(db_path=str(tmp_path / "user_exit_workflows.db"))
    audit_entries: list[dict[str, str]] = []
    refreshed_users: list[list[str]] = []

    class FakeEntraProvider:
        @staticmethod
        def remove_direct_cloud_group_memberships(user_id):
            return {
                "summary": f"Removed direct cloud groups for {user_id}",
                "before_summary": {"direct_group_count": 2},
                "after_summary": {"removed_group_count": 2},
            }

        @staticmethod
        def remove_all_direct_licenses(user_id):
            return {
                "summary": f"Removed direct licenses for {user_id}",
                "before_summary": {"license_count": 1},
                "after_summary": {"license_count": 0},
            }

    class FakeProviders:
        entra = FakeEntraProvider()

        @staticmethod
        def get_user_detail(user_id):
            return {
                "id": user_id,
                "display_name": "Cloud User",
                "principal_name": "cloud@example.com",
                "mail": "cloud@example.com",
                "job_title": "IT Tech",
                "on_prem_sync": False,
                "on_prem_domain": "",
                "on_prem_netbios": "",
                "on_prem_sam_account_name": "",
                "on_prem_distinguished_name": "",
            }

        @staticmethod
        def list_licenses(user_id):
            return [{"sku_id": "sku-1", "sku_part_number": "EMS", "display_name": "EMS"}]

        @staticmethod
        def list_devices(user_id):
            return []

        @staticmethod
        def get_mailbox(user_id):
            return {"primary_address": ""}

        @staticmethod
        def execute(action_type, user_id, params):
            del params
            return {
                "summary": f"{action_type} completed for {user_id}",
                "before_summary": {"action": action_type, "before": True},
                "after_summary": {"action": action_type, "after": True},
            }

    class FakeJobs:
        @staticmethod
        def record_audit_entry(**kwargs):
            audit_entries.append(kwargs)

    class FakeAzureCache:
        @staticmethod
        def refresh_directory_users(user_ids):
            refreshed_users.append(list(user_ids))

    monkeypatch.setattr("user_exit_workflows.user_admin_providers", FakeProviders())
    monkeypatch.setattr("user_exit_workflows.user_admin_jobs", FakeJobs())
    monkeypatch.setattr("user_exit_workflows.azure_cache", FakeAzureCache())

    workflow = manager.create_workflow(
        user_id="user-1",
        typed_upn_confirmation="cloud@example.com",
        on_prem_sam_account_name_override="",
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    while True:
        claimed = manager._claim_next_local_step()
        if not claimed:
            break
        manager._process_local_step(claimed["workflow"], claimed["step"])

    updated = manager.get_workflow(workflow["workflow_id"])
    assert updated is not None
    assert updated["status"] == "awaiting_manual"
    assert [step["status"] for step in updated["steps"]] == [
        "completed",
        "completed",
        "completed",
        "completed",
        "skipped",
        "skipped",
        "completed",
    ]
    assert len(audit_entries) == 5
    assert refreshed_users == [["user-1"], ["user-1"], ["user-1"], ["user-1"], ["user-1"]]

    for task in list(updated["manual_tasks"]):
        updated = manager.complete_manual_task(
            workflow["workflow_id"],
            task["task_id"],
            actor_email="tech@example.com",
            actor_name="Tech User",
            notes="done",
        )

    assert updated["status"] == "completed"
    assert all(task["status"] == "completed" for task in updated["manual_tasks"])


def test_agent_claim_heartbeat_complete_and_restart_requeue(tmp_path, monkeypatch):
    db_path = str(tmp_path / "user_exit_workflows.db")
    manager = UserExitWorkflowManager(db_path=db_path)

    class FakeEntraProvider:
        @staticmethod
        def remove_direct_cloud_group_memberships(user_id):
            return {"summary": "Removed groups", "before_summary": {}, "after_summary": {}}

        @staticmethod
        def remove_all_direct_licenses(user_id):
            return {"summary": "Removed licenses", "before_summary": {}, "after_summary": {}}

    class FakeProviders:
        entra = FakeEntraProvider()

        @staticmethod
        def get_user_detail(user_id):
            return {
                "id": user_id,
                "display_name": "Hybrid User",
                "principal_name": "hybrid@canyon.example",
                "mail": "hybrid@canyon.example",
                "job_title": "Operations",
                "on_prem_sync": True,
                "on_prem_domain": "canyon.local",
                "on_prem_netbios": "CANYON",
                "on_prem_sam_account_name": "hybrid.user",
                "on_prem_distinguished_name": "CN=Hybrid User,OU=Users,DC=canyon,DC=local",
            }

        @staticmethod
        def list_licenses(user_id):
            return []

        @staticmethod
        def list_devices(user_id):
            return []

        @staticmethod
        def get_mailbox(user_id):
            return {"primary_address": "hybrid@canyon.example"}

        @staticmethod
        def execute(action_type, user_id, params):
            del params
            return {"summary": f"{action_type} completed", "before_summary": {}, "after_summary": {}}

    class FakeJobs:
        @staticmethod
        def record_audit_entry(**kwargs):
            return None

    class FakeAzureCache:
        @staticmethod
        def refresh_directory_users(user_ids):
            return None

    monkeypatch.setattr("user_exit_workflows.user_admin_providers", FakeProviders())
    monkeypatch.setattr("user_exit_workflows.user_admin_jobs", FakeJobs())
    monkeypatch.setattr("user_exit_workflows.azure_cache", FakeAzureCache())

    workflow = manager.create_workflow(
        user_id="user-2",
        typed_upn_confirmation="hybrid@canyon.example",
        on_prem_sam_account_name_override="",
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    step = None
    while True:
        step = manager.claim_agent_step(agent_id="agent-1", profile_keys=["canyon"])
        if step:
            break
        claimed = manager._claim_next_local_step()
        assert claimed is not None
        manager._process_local_step(claimed["workflow"], claimed["step"])

    assert step is not None
    assert step["step_key"] == "exit_on_prem_deprovision"

    manager.heartbeat_agent_step(step_id=step["step_id"], agent_id="agent-1")
    updated = manager.complete_agent_step(
        step_id=step["step_id"],
        agent_id="agent-1",
        status="completed",
        summary="Disabled AD account and moved to disabled OU",
        error="",
        before_summary={"enabled": True},
        after_summary={"enabled": False},
    )
    assert any(item["step_key"] == "exit_on_prem_deprovision" and item["status"] == "completed" for item in updated["steps"])

    mailbox_step = manager.claim_agent_step(agent_id="agent-1", profile_keys=["canyon"])
    assert mailbox_step is not None
    assert mailbox_step["step_key"] == "mailbox_convert_type"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE user_exit_steps
            SET status = 'running',
                assigned_agent_id = 'agent-2',
                lease_expires_at = '2000-01-01T00:00:00+00:00'
            WHERE step_id = ?
            """,
            (mailbox_step["step_id"],),
        )
        conn.commit()

    restarted = UserExitWorkflowManager(db_path=db_path)
    reloaded = restarted.get_workflow(workflow["workflow_id"])
    assert reloaded is not None
    assert any(item["step_key"] == "mailbox_convert_type" and item["status"] == "queued" for item in reloaded["steps"])
