from __future__ import annotations

from typing import Any

import pytest

from onedrive_copy_jobs import OneDriveCopyJobManager


class FakeOneDriveClient:
    def __init__(self, *, tree: dict[str, list[dict[str, Any]]], batch_responses: list[dict[str, Any]] | None = None) -> None:
        self.tree = tree
        self.batch_responses = list(batch_responses or [])
        self.created_folders: list[tuple[str, str, str]] = []
        self.batch_payloads: list[list[dict[str, Any]]] = []

    def get_user_drive(self, user_id: str) -> dict[str, Any]:
        return {"id": f"drive-{user_id}"}

    def get_user_drive_root(self, user_id: str) -> dict[str, Any]:
        return {"id": "source-root" if "source" in user_id else "dest-root"}

    def create_user_drive_folder(self, user_id: str, parent_id: str, name: str) -> dict[str, Any]:
        self.created_folders.append((user_id, parent_id, name))
        return {"id": f"folder-{len(self.created_folders)}", "name": name}

    def list_user_drive_children(self, user_id: str, folder_id: str) -> list[dict[str, Any]]:
        del user_id
        return [dict(item) for item in self.tree.get(folder_id, [])]

    def graph_batch_request(self, requests_payload: list[dict[str, Any]]) -> dict[str, Any]:
        self.batch_payloads.append([dict(item) for item in requests_payload])
        if self.batch_responses:
            return self.batch_responses.pop(0)
        return {"responses": [{"id": str(item["id"]), "status": 202} for item in requests_payload]}


def test_create_job_rejects_same_source_and_destination(tmp_path):
    manager = OneDriveCopyJobManager(db_path=str(tmp_path / "onedrive_copy_jobs.db"))

    with pytest.raises(ValueError, match="must be different"):
        manager.create_job(
            site_scope="primary",
            source_upn="same@example.com",
            destination_upn="same@example.com",
            destination_folder="CopiedFiles",
            test_mode=False,
            test_file_limit=25,
            exclude_system_folders=True,
            requested_by_email="tech@example.com",
            requested_by_name="Tech User",
        )


def test_create_job_saves_recent_upns_for_future_dropdown_reuse(tmp_path):
    manager = OneDriveCopyJobManager(db_path=str(tmp_path / "onedrive_copy_jobs.db"))

    manager.create_job(
        site_scope="primary",
        source_upn="Former.User@example.com",
        destination_upn="dest@example.com",
        destination_folder="CopiedFiles",
        test_mode=False,
        test_file_limit=25,
        exclude_system_folders=True,
        requested_by_email="gallison@movedocs.com",
        requested_by_name="Gallison",
    )

    saved = manager.list_saved_user_options(limit=10)

    assert [row["principal_name"] for row in saved] == [
        "dest@example.com",
        "Former.User@example.com",
    ]
    assert saved[0]["source"] == "saved"
    assert saved[1]["source"] == "saved"


def test_remember_user_option_enriches_saved_rows_and_searches_by_upn(tmp_path):
    manager = OneDriveCopyJobManager(db_path=str(tmp_path / "onedrive_copy_jobs.db"))
    manager.remember_user_option(
        "wayne.berry@librasolutionsgroup.com",
        display_name="Wayne Berry",
        principal_name="wayne.berry@librasolutionsgroup.com",
        mail="wayne.berry@librasolutionsgroup.com",
        source_hint="entra",
        used_by_email="wberry@movedocs.com",
    )

    saved = manager.list_saved_user_options(search="wayne", limit=10)

    assert saved == [
        {
            "id": "saved:wayne.berry@librasolutionsgroup.com",
            "display_name": "Wayne Berry",
            "principal_name": "wayne.berry@librasolutionsgroup.com",
            "mail": "wayne.berry@librasolutionsgroup.com",
            "enabled": None,
            "source": "saved",
            "last_used_at": saved[0]["last_used_at"],
        }
    ]


def test_process_job_preserves_empty_folders_and_excludes_system_roots(tmp_path, monkeypatch):
    tree = {
        "source-root": [
            {"id": "folder-empty", "name": "EmptyFolder", "folder": {}},
            {"id": "folder-docs", "name": "Docs", "folder": {}},
            {"id": "folder-apps", "name": "Apps", "folder": {}},
            {"id": "file-root", "name": "root.txt"},
        ],
        "folder-empty": [],
        "folder-docs": [{"id": "file-doc-1", "name": "child.docx"}],
        "folder-apps": [{"id": "file-app-1", "name": "skip.me"}],
    }
    fake_client = FakeOneDriveClient(tree=tree)
    manager = OneDriveCopyJobManager(
        db_path=str(tmp_path / "onedrive_copy_jobs.db"),
        client_factory=lambda: fake_client,
    )
    monkeypatch.setattr("onedrive_copy_jobs.time.sleep", lambda _seconds: None)

    job = manager.create_job(
        site_scope="primary",
        source_upn="source@example.com",
        destination_upn="dest@example.com",
        destination_folder="CopiedFiles",
        test_mode=False,
        test_file_limit=25,
        exclude_system_folders=True,
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    manager._process_job(job["job_id"])
    updated = manager.get_job(job["job_id"], include_events=True)

    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["total_folders_found"] == 2
    assert updated["total_files_found"] == 2
    assert updated["folders_created"] == 2
    assert updated["files_dispatched"] == 2
    assert updated["files_failed"] == 0
    created_names = [name for _, _, name in fake_client.created_folders]
    assert "CopiedFiles" in created_names
    assert "EmptyFolder" in created_names
    assert "Docs" in created_names
    assert "Apps" not in created_names
    assert any("Skipped root system folder 'Apps'." in event["message"] for event in updated["events"])


def test_process_job_limits_test_mode_files_and_batches_dispatches(tmp_path, monkeypatch):
    tree = {
        "source-root": [
            *(
                {"id": f"file-root-{index}", "name": f"file-root-{index}.txt"}
                for index in range(10)
            ),
            {"id": "folder-picked", "name": "Picked", "folder": {}},
            {"id": "folder-skipped", "name": "Skipped", "folder": {}},
        ],
        "folder-picked": [
            {"id": "picked-file-1", "name": "picked-1.txt"},
            {"id": "picked-file-2", "name": "picked-2.txt"},
        ],
        "folder-skipped": [
            {"id": "skipped-file-1", "name": "skip-1.txt"},
        ],
    }
    fake_client = FakeOneDriveClient(tree=tree)
    manager = OneDriveCopyJobManager(
        db_path=str(tmp_path / "onedrive_copy_jobs.db"),
        client_factory=lambda: fake_client,
    )
    monkeypatch.setattr("onedrive_copy_jobs.time.sleep", lambda _seconds: None)

    job = manager.create_job(
        site_scope="azure",
        source_upn="source@example.com",
        destination_upn="dest@example.com",
        destination_folder="CopiedFiles",
        test_mode=True,
        test_file_limit=5,
        exclude_system_folders=True,
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    manager._process_job(job["job_id"])
    updated = manager.get_job(job["job_id"], include_events=True)

    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["total_files_found"] == 13
    assert updated["files_dispatched"] == 5
    assert len(fake_client.batch_payloads) == 1
    assert len(fake_client.batch_payloads[0]) == 5
    created_names = [name for _, _, name in fake_client.created_folders]
    assert "Picked" not in created_names
    assert "Skipped" not in created_names
    assert any("Test mode enabled" in event["message"] for event in updated["events"])


def test_test_mode_only_creates_folders_needed_for_selected_files(tmp_path, monkeypatch):
    tree = {
        "source-root": [
            {"id": "folder-picked", "name": "Picked", "folder": {}},
            {"id": "folder-skipped", "name": "Skipped", "folder": {}},
        ],
        "folder-picked": [{"id": "picked-file-1", "name": "picked-1.txt"}],
        "folder-skipped": [{"id": "skip-file-1", "name": "skip-1.txt"}],
    }
    fake_client = FakeOneDriveClient(tree=tree)
    manager = OneDriveCopyJobManager(
        db_path=str(tmp_path / "onedrive_copy_jobs.db"),
        client_factory=lambda: fake_client,
    )
    monkeypatch.setattr("onedrive_copy_jobs.time.sleep", lambda _seconds: None)

    job = manager.create_job(
        site_scope="primary",
        source_upn="source@example.com",
        destination_upn="dest@example.com",
        destination_folder="CopiedFiles",
        test_mode=True,
        test_file_limit=1,
        exclude_system_folders=True,
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    manager._process_job(job["job_id"])
    updated = manager.get_job(job["job_id"], include_events=True)

    assert updated is not None
    assert updated["status"] == "completed"
    created_names = [name for _, _, name in fake_client.created_folders]
    assert "CopiedFiles" in created_names
    assert "Picked" in created_names
    assert "Skipped" not in created_names


def test_process_job_includes_system_folders_when_requested_and_batches_by_ten(tmp_path, monkeypatch):
    tree = {
        "source-root": (
            [{"id": "folder-apps", "name": "Apps", "folder": {}}]
            + [{"id": f"file-{index}", "name": f"file-{index}.txt"} for index in range(12)]
        ),
        "folder-apps": [],
    }
    fake_client = FakeOneDriveClient(tree=tree)
    manager = OneDriveCopyJobManager(
        db_path=str(tmp_path / "onedrive_copy_jobs.db"),
        client_factory=lambda: fake_client,
    )
    monkeypatch.setattr("onedrive_copy_jobs.time.sleep", lambda _seconds: None)

    job = manager.create_job(
        site_scope="primary",
        source_upn="source@example.com",
        destination_upn="dest@example.com",
        destination_folder="CopiedFiles",
        test_mode=False,
        test_file_limit=25,
        exclude_system_folders=False,
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    manager._process_job(job["job_id"])
    updated = manager.get_job(job["job_id"], include_events=True)

    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["total_folders_found"] == 1
    assert updated["total_files_found"] == 12
    created_names = [name for _, _, name in fake_client.created_folders]
    assert "Apps" in created_names
    assert len(fake_client.batch_payloads) == 2
    assert len(fake_client.batch_payloads[0]) == 10
    assert len(fake_client.batch_payloads[1]) == 2


def test_process_job_retries_only_throttled_items_and_records_failures(tmp_path, monkeypatch):
    tree = {
        "source-root": [
            {"id": "file-1", "name": "first.txt"},
            {"id": "file-2", "name": "second.txt"},
            {"id": "file-3", "name": "third.txt"},
        ]
    }
    fake_client = FakeOneDriveClient(
        tree=tree,
        batch_responses=[
            {
                "responses": [
                    {"id": "1", "status": 202},
                    {"id": "2", "status": 429},
                    {"id": "3", "status": 500, "body": {"error": {"message": "Boom"}}},
                ]
            },
            {
                "responses": [
                    {"id": "2", "status": 202},
                ]
            },
        ],
    )
    manager = OneDriveCopyJobManager(
        db_path=str(tmp_path / "onedrive_copy_jobs.db"),
        client_factory=lambda: fake_client,
    )
    monkeypatch.setattr("onedrive_copy_jobs.time.sleep", lambda _seconds: None)

    job = manager.create_job(
        site_scope="primary",
        source_upn="source@example.com",
        destination_upn="dest@example.com",
        destination_folder="CopiedFiles",
        test_mode=False,
        test_file_limit=25,
        exclude_system_folders=True,
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    manager._process_job(job["job_id"])
    updated = manager.get_job(job["job_id"], include_events=True)

    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["files_dispatched"] == 2
    assert updated["files_failed"] == 1
    assert len(fake_client.batch_payloads) == 2
    assert len(fake_client.batch_payloads[0]) == 3
    assert len(fake_client.batch_payloads[1]) == 1
    assert any(event["level"] == "warning" for event in updated["events"])
    assert any("Dispatch failed for 'third.txt'" in event["message"] for event in updated["events"])
