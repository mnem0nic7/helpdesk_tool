from __future__ import annotations

from pathlib import Path

from security_device_jobs import SecurityDeviceJobError, SecurityDeviceJobManager


class _StubProviderRegistry:
    def __init__(self):
        class _Provider:
            enabled = True

            @staticmethod
            def execute(action_type, user_id, params):
                del user_id
                device_ids = params.get("device_ids") or []
                return {
                    "provider": "device_management",
                    "summary": f"Queued {action_type} for {len(device_ids)} device(s)",
                    "before_summary": {"device_ids": device_ids},
                    "after_summary": {"action": action_type},
                }

        self._provider = _Provider()

    def provider_for_action(self, action_type):
        return self._provider, "device_management"

    def execute(self, action_type, user_id, params):
        return self._provider.execute(action_type, user_id, params)


class _StubAzureCache:
    def __init__(self):
        self.refresh_calls = []

    def _snapshot(self, key):
        assert key == "managed_devices"
        return [
            {
                "id": "device-1",
                "device_name": "Payroll Laptop",
                "azure_ad_device_id": "aad-1",
            },
            {
                "id": "device-2",
                "device_name": "Warehouse Tablet",
                "azure_ad_device_id": "aad-2",
            },
        ]

    def refresh_datasets(self, dataset_keys, force=False):
        self.refresh_calls.append((tuple(dataset_keys), force))


def test_device_job_manager_requires_destructive_confirmation(tmp_path, monkeypatch):
    manager = SecurityDeviceJobManager(db_path=str(Path(tmp_path) / "security_device_jobs.db"))
    monkeypatch.setattr("security_device_jobs.user_admin_providers", _StubProviderRegistry())
    monkeypatch.setattr("security_device_jobs.azure_cache", _StubAzureCache())

    try:
        manager.create_job(
            action_type="device_wipe",
            device_ids=["device-1", "device-2"],
            reason="Incident response",
            params={},
            confirm_device_count=2,
            confirm_device_names=["Payroll Laptop"],
            requested_by_email="tech@example.com",
            requested_by_name="Tech User",
        )
    except SecurityDeviceJobError as exc:
        assert "exact selected device names" in str(exc)
    else:
        raise AssertionError("Expected destructive confirmation failure")


def test_device_job_manager_processes_queued_actions(tmp_path, monkeypatch):
    manager = SecurityDeviceJobManager(db_path=str(Path(tmp_path) / "security_device_jobs.db"))
    stub_cache = _StubAzureCache()
    monkeypatch.setattr("security_device_jobs.user_admin_providers", _StubProviderRegistry())
    monkeypatch.setattr("security_device_jobs.azure_cache", stub_cache)

    job = manager.create_job(
        action_type="device_sync",
        device_ids=["device-1"],
        reason="Compliance drift",
        params={},
        confirm_device_count=None,
        confirm_device_names=None,
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    claimed = manager._claim_next_job()
    assert claimed is not None
    manager._process_job(job["job_id"])

    stored_job = manager.get_job(job["job_id"])
    assert stored_job is not None
    assert stored_job["status"] == "completed"
    assert stored_job["success_count"] == 1

    results = manager.get_job_results(job["job_id"])
    assert len(results) == 1
    assert results[0]["device_name"] == "Payroll Laptop"
    assert results[0]["success"] is True
    assert stub_cache.refresh_calls == [(("device_compliance",), True)]


def test_device_job_manager_requires_primary_user_id_for_reassignment(tmp_path, monkeypatch):
    manager = SecurityDeviceJobManager(db_path=str(Path(tmp_path) / "security_device_jobs.db"))
    monkeypatch.setattr("security_device_jobs.user_admin_providers", _StubProviderRegistry())
    monkeypatch.setattr("security_device_jobs.azure_cache", _StubAzureCache())

    try:
        manager.create_job(
            action_type="device_reassign_primary_user",
            device_ids=["device-1"],
            reason="Assign owner",
            params={},
            confirm_device_count=None,
            confirm_device_names=None,
            requested_by_email="tech@example.com",
            requested_by_name="Tech User",
        )
    except SecurityDeviceJobError as exc:
        assert "primary_user_id" in str(exc)
    else:
        raise AssertionError("Expected primary-user validation failure")


def test_device_job_manager_creates_and_reports_batch_status(tmp_path, monkeypatch):
    manager = SecurityDeviceJobManager(db_path=str(Path(tmp_path) / "security_device_jobs.db"))
    monkeypatch.setattr("security_device_jobs.user_admin_providers", _StubProviderRegistry())
    monkeypatch.setattr("security_device_jobs.azure_cache", _StubAzureCache())

    batch = manager.create_batch(
        plan_items=[
            {
                "device_id": "device-1",
                "device_name": "Payroll Laptop",
                "action_type": "device_sync",
                "params": {},
            },
            {
                "device_id": "device-2",
                "device_name": "Warehouse Tablet",
                "action_type": "device_reassign_primary_user",
                "params": {"primary_user_id": "user-2", "primary_user_display_name": "Grace Hopper"},
                "assignment_user_id": "user-2",
                "assignment_user_display_name": "Grace Hopper",
            },
        ],
        reason="Smart remediation",
        confirm_device_count=None,
        confirm_device_names=None,
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    assert batch["item_count"] == 2
    assert len(batch["child_jobs"]) == 2
    assert batch["status"] == "queued"

    child_jobs = [manager._claim_next_job(), manager._claim_next_job()]
    for child_job in child_jobs:
        assert child_job is not None
        manager._process_job(child_job["job_id"])

    stored_batch = manager.get_batch(batch["batch_id"])
    assert stored_batch is not None
    assert stored_batch["status"] == "completed"
    assert stored_batch["results_ready"] is True

    results = manager.get_batch_results(batch["batch_id"])
    assert len(results) == 2
    assert {item["action_type"] for item in results} == {"device_sync", "device_reassign_primary_user"}
    assignment_result = next(item for item in results if item["action_type"] == "device_reassign_primary_user")
    assert assignment_result["assignment_user_display_name"] == "Grace Hopper"
