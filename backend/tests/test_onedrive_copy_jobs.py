from __future__ import annotations

from typing import Any
import sqlite3

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


class _PostgresSqliteProxy:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _translate(sql: str) -> str:
        return sql.replace("%s", "?")

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._conn.execute(self._translate(sql), params)

    def executemany(self, sql: str, seq_of_params: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        return self._conn.executemany(self._translate(sql), seq_of_params)

    def executescript(self, sql: str) -> sqlite3.Cursor:
        return self._conn.executescript(sql)

    def commit(self) -> None:
        self._conn.commit()

    def __enter__(self) -> _PostgresSqliteProxy:
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return self._conn.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


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


def test_clear_finished_jobs_removes_completed_and_failed_history_only(tmp_path):
    manager = OneDriveCopyJobManager(db_path=str(tmp_path / "onedrive_copy_jobs.db"))
    with manager._conn() as conn:
        conn.executemany(
            """
            INSERT INTO onedrive_copy_jobs (
                job_id,
                site_scope,
                status,
                phase,
                requested_by_email,
                requested_by_name,
                source_upn,
                destination_upn,
                destination_folder,
                requested_at,
                completed_at,
                progress_message
            )
            VALUES (?, 'primary', ?, ?, 'user@example.com', 'User', 'source@example.com', 'dest@example.com', 'Copied', ?, ?, ?)
            """,
            [
                ("job-running", "running", "enumerating", "2026-03-31T18:00:00Z", None, "Working"),
                ("job-completed", "completed", "completed", "2026-03-31T18:01:00Z", "2026-03-31T18:05:00Z", "Done"),
                ("job-failed", "failed", "failed", "2026-03-31T18:02:00Z", "2026-03-31T18:06:00Z", "Failed"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO onedrive_copy_job_events (job_id, level, message, created_at)
            VALUES (?, 'info', ?, '2026-03-31T18:05:00Z')
            """,
            [
                ("job-completed", "Completed"),
                ("job-failed", "Failed"),
            ],
        )
        conn.commit()

    deleted_count = manager.clear_finished_jobs()

    assert deleted_count == 2
    remaining_jobs = manager.list_jobs(limit=10)
    assert [job["job_id"] for job in remaining_jobs] == ["job-running"]


def test_postgres_mode_backfills_legacy_jobs_and_requeues_running_jobs(tmp_path, monkeypatch):
    legacy_db_path = tmp_path / "onedrive_copy_jobs.db"
    postgres_db_path = tmp_path / "onedrive_copy_jobs_postgres.db"

    legacy_manager = OneDriveCopyJobManager(db_path=str(legacy_db_path))
    with legacy_manager._conn() as conn:
        conn.execute(
            """
            INSERT INTO onedrive_copy_jobs (
                job_id,
                site_scope,
                status,
                phase,
                requested_by_email,
                requested_by_name,
                source_upn,
                destination_upn,
                destination_folder,
                test_mode,
                test_file_limit,
                exclude_system_folders,
                requested_at,
                started_at,
                progress_current,
                progress_total,
                progress_message
            )
            VALUES (?, ?, 'running', 'enumerating', ?, ?, ?, ?, ?, 1, 3, 1, ?, ?, 2, 3, 'Working')
            """,
            (
                "job-running",
                "primary",
                "user@example.com",
                "Example User",
                "source@example.com",
                "dest@example.com",
                "CopiedFiles",
                "2026-03-26T00:00:00+00:00",
                "2026-03-26T00:01:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO onedrive_copy_job_events (
                job_id,
                level,
                message,
                created_at
            )
            VALUES (?, 'info', ?, ?)
            """,
            ("job-running", "Queued copy request", "2026-03-26T00:00:05+00:00"),
        )
        conn.execute(
            """
            INSERT INTO onedrive_copy_saved_upns (
                normalized_upn,
                display_name,
                principal_name,
                mail,
                source_hint,
                created_at,
                updated_at,
                last_used_at,
                last_used_by_email
            )
            VALUES (?, ?, ?, ?, 'manual', ?, ?, ?, ?)
            """,
            (
                "source@example.com",
                "Source User",
                "source@example.com",
                "source@example.com",
                "2026-03-26T00:00:10+00:00",
                "2026-03-26T00:00:10+00:00",
                "2026-03-26T00:00:10+00:00",
                "tech@example.com",
            ),
        )
        conn.commit()

    monkeypatch.setattr("onedrive_copy_jobs.DATA_DIR", tmp_path)
    monkeypatch.setattr("onedrive_copy_jobs.postgres_enabled", lambda: True)

    def create_postgres_schema() -> None:
        with sqlite3.connect(postgres_db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS onedrive_copy_jobs (
                    job_id TEXT PRIMARY KEY,
                    site_scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    requested_by_email TEXT NOT NULL,
                    requested_by_name TEXT NOT NULL,
                    source_upn TEXT NOT NULL,
                    destination_upn TEXT NOT NULL,
                    destination_folder TEXT NOT NULL,
                    test_mode INTEGER NOT NULL DEFAULT 0,
                    test_file_limit INTEGER NOT NULL DEFAULT 25,
                    exclude_system_folders INTEGER NOT NULL DEFAULT 1,
                    requested_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT NOT NULL DEFAULT '',
                    total_folders_found INTEGER NOT NULL DEFAULT 0,
                    total_files_found INTEGER NOT NULL DEFAULT 0,
                    folders_created INTEGER NOT NULL DEFAULT 0,
                    files_dispatched INTEGER NOT NULL DEFAULT 0,
                    files_failed INTEGER NOT NULL DEFAULT 0,
                    source_drive_id TEXT NOT NULL DEFAULT '',
                    destination_drive_id TEXT NOT NULL DEFAULT '',
                    destination_top_folder_id TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS onedrive_copy_job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS onedrive_copy_saved_upns (
                    normalized_upn TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    principal_name TEXT NOT NULL DEFAULT '',
                    mail TEXT NOT NULL DEFAULT '',
                    source_hint TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    last_used_by_email TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_onedrive_copy_jobs_requested_at
                    ON onedrive_copy_jobs (requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_onedrive_copy_events_job
                    ON onedrive_copy_job_events (job_id, event_id DESC);
                CREATE INDEX IF NOT EXISTS idx_onedrive_copy_saved_upns_last_used
                    ON onedrive_copy_saved_upns (last_used_at DESC);
                """
            )

    monkeypatch.setattr("onedrive_copy_jobs.ensure_postgres_schema", create_postgres_schema)

    def fake_connect_postgres(*, row_factory=sqlite3.Row):
        conn = sqlite3.connect(postgres_db_path)
        conn.row_factory = row_factory
        return _PostgresSqliteProxy(conn)

    monkeypatch.setattr("onedrive_copy_jobs.connect_postgres", fake_connect_postgres)

    manager = OneDriveCopyJobManager()
    job = manager.get_job("job-running")
    saved_before = manager.list_saved_user_options(limit=10)
    created = manager.create_job(
        site_scope="azure",
        source_upn="fresh.source@example.com",
        destination_upn="fresh.dest@example.com",
        destination_folder="CopiedFiles",
        test_mode=False,
        test_file_limit=25,
        exclude_system_folders=True,
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    assert manager._use_postgres is True
    assert job is not None
    assert job["status"] == "queued"
    assert job["phase"] == "queued"
    assert job["progress_current"] == 0
    assert job["progress_message"] == "Re-queued after restart"
    assert saved_before == [
        {
            "id": "saved:source@example.com",
            "display_name": "Source User",
            "principal_name": "source@example.com",
            "mail": "source@example.com",
            "enabled": None,
            "source": "saved",
            "last_used_at": "2026-03-26T00:00:10+00:00",
        }
    ]
    assert created["status"] == "queued"
    assert manager.get_job(created["job_id"]) is not None


def test_explicit_db_path_keeps_sqlite_fallback_when_postgres_is_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr("onedrive_copy_jobs.postgres_enabled", lambda: True)

    def fail_connect_postgres(*args, **kwargs):
        raise AssertionError("connect_postgres should not be used when db_path is explicit")

    monkeypatch.setattr("onedrive_copy_jobs.connect_postgres", fail_connect_postgres)

    manager = OneDriveCopyJobManager(db_path=str(tmp_path / "onedrive_copy_jobs.db"))

    assert manager._use_postgres is False
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

    assert job["status"] == "queued"
    assert manager.get_job(job["job_id"]) is not None


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
