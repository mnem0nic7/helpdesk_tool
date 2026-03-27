from __future__ import annotations

import json
import sqlite3

import user_admin_jobs as user_admin_jobs_module
from user_admin_jobs import UserAdminJobManager
from user_admin_providers import UserAdminProviderError


class _EnabledProvider:
    enabled = True


class _FakePostgresConnection:
    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE user_admin_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                action_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                target_user_ids_json TEXT NOT NULL,
                params_json TEXT NOT NULL,
                requested_by_email TEXT NOT NULL,
                requested_by_name TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                progress_current INTEGER NOT NULL DEFAULT 0,
                progress_total INTEGER NOT NULL DEFAULT 0,
                progress_message TEXT NOT NULL DEFAULT '',
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE user_admin_job_results (
                id INTEGER PRIMARY KEY,
                job_id TEXT NOT NULL,
                target_user_id TEXT NOT NULL,
                target_display_name TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL,
                success INTEGER NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                before_summary_json TEXT NOT NULL DEFAULT '{}',
                after_summary_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE user_admin_audit (
                audit_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                actor_email TEXT NOT NULL,
                actor_name TEXT NOT NULL DEFAULT '',
                target_user_id TEXT NOT NULL,
                target_display_name TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL,
                action_type TEXT NOT NULL,
                params_summary_json TEXT NOT NULL DEFAULT '{}',
                before_summary_json TEXT NOT NULL DEFAULT '{}',
                after_summary_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )

    def execute(self, sql, params=()):
        statement = str(sql).strip()
        if statement.startswith("SELECT setval("):
            return self._conn.execute("SELECT 1 AS ok")
        return self._conn.execute(statement.replace("%s", "?"), params)

    def executemany(self, sql, seq_of_params):
        return self._conn.executemany(str(sql).replace("%s", "?"), seq_of_params)

    def commit(self):
        self._conn.commit()

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        return False


def test_create_job_redacts_sensitive_params_in_storage(tmp_path, monkeypatch):
    manager = UserAdminJobManager(db_path=str(tmp_path / "user_admin_jobs.db"))

    class FakeProviders:
        @staticmethod
        def provider_for_action(action_type):
            assert action_type == "reset_password"
            return _EnabledProvider(), "entra"

    monkeypatch.setattr("user_admin_jobs.user_admin_providers", FakeProviders())

    job = manager.create_job(
        action_type="reset_password",
        target_user_ids=["user-1"],
        params={"new_password": "SuperSecret!123", "force_change_on_next_login": True},
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    assert job["status"] == "queued"
    assert manager._params_for_job(job["job_id"])["new_password"] == "SuperSecret!123"

    with sqlite3.connect(str(tmp_path / "user_admin_jobs.db")) as conn:
        row = conn.execute("SELECT params_json FROM user_admin_jobs WHERE job_id = ?", (job["job_id"],)).fetchone()

    assert row is not None
    persisted = json.loads(str(row[0]))
    assert persisted["new_password"] == "[redacted]"


def test_running_jobs_are_requeued_on_manager_startup(tmp_path):
    db_path = str(tmp_path / "user_admin_jobs.db")
    manager = UserAdminJobManager(db_path=db_path)

    with manager._conn() as conn:
        conn.execute(
            """
            INSERT INTO user_admin_jobs (
                job_id,
                status,
                action_type,
                provider,
                target_user_ids_json,
                params_json,
                requested_by_email,
                requested_by_name,
                requested_at,
                started_at,
                progress_current,
                progress_total,
                progress_message
            )
            VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, 1, 2, 'Working')
            """,
            (
                "job-running",
                "disable_sign_in",
                "entra",
                json.dumps(["user-1", "user-2"]),
                "{}",
                "tech@example.com",
                "Tech User",
                "2026-03-19T00:00:00+00:00",
                "2026-03-19T00:01:00+00:00",
            ),
        )
        conn.commit()

    restarted = UserAdminJobManager(db_path=db_path)
    job = restarted.get_job("job-running")

    assert job is not None
    assert job["status"] == "queued"
    assert job["progress_current"] == 0
    assert job["progress_message"] == "Re-queued after restart"


def test_process_job_records_one_time_secret_without_persisting_it(tmp_path, monkeypatch):
    manager = UserAdminJobManager(db_path=str(tmp_path / "user_admin_jobs.db"))

    class FakeProviders:
        @staticmethod
        def provider_for_action(action_type):
            assert action_type == "reset_password"
            return _EnabledProvider(), "entra"

        @staticmethod
        def execute(action_type, user_id, params):
            assert action_type == "reset_password"
            assert params["force_change_on_next_login"] is True
            return {
                "provider": "entra",
                "summary": f"Reset password for {user_id}",
                "before_summary": {},
                "after_summary": {"force_change_on_next_login": True},
                "one_time_secret": "TempPass!123",
            }

    monkeypatch.setattr("user_admin_jobs.user_admin_providers", FakeProviders())
    monkeypatch.setattr("user_admin_jobs.azure_cache.list_directory_objects", lambda snapshot, search="": [{"id": "user-1", "display_name": "Ada Lovelace"}] if snapshot == "users" else [])
    refreshed: list[list[str]] = []
    monkeypatch.setattr("user_admin_jobs.azure_cache.refresh_directory_users", lambda user_ids: refreshed.append(list(user_ids)))

    job = manager.create_job(
        action_type="reset_password",
        target_user_ids=["user-1"],
        params={"force_change_on_next_login": True},
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    manager._process_job(job["job_id"])

    updated = manager.get_job(job["job_id"])
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["one_time_results_available"] is True
    assert refreshed == [["user-1"]]

    first_results = manager.get_job_results(job["job_id"])
    assert first_results[0]["one_time_secret"] == "TempPass!123"

    second_results = manager.get_job_results(job["job_id"])
    assert second_results[0]["one_time_secret"] is None

    with manager._conn() as conn:
        row = conn.execute(
            "SELECT after_summary_json FROM user_admin_job_results WHERE job_id = ?",
            (job["job_id"],),
        ).fetchone()
    assert row is not None
    assert "TempPass!123" not in str(row[0])


def test_process_job_retries_and_records_partial_failures(tmp_path, monkeypatch):
    manager = UserAdminJobManager(db_path=str(tmp_path / "user_admin_jobs.db"))
    call_count = {"user-1": 0, "user-2": 0}

    class FakeProviders:
        @staticmethod
        def provider_for_action(action_type):
            assert action_type == "disable_sign_in"
            return _EnabledProvider(), "entra"

        @staticmethod
        def execute(action_type, user_id, params):
            del action_type, params
            call_count[user_id] += 1
            if user_id == "user-1" and call_count[user_id] == 1:
                raise UserAdminProviderError("429 throttled", retry_after_seconds=0)
            if user_id == "user-2":
                raise UserAdminProviderError("User update failed")
            return {
                "provider": "entra",
                "summary": "Disabled sign-in",
                "before_summary": {"enabled": True},
                "after_summary": {"enabled": False},
            }

    monkeypatch.setattr("user_admin_jobs.user_admin_providers", FakeProviders())
    monkeypatch.setattr(
        "user_admin_jobs.azure_cache.list_directory_objects",
        lambda snapshot, search="": [
            {"id": "user-1", "display_name": "Ada Lovelace"},
            {"id": "user-2", "display_name": "Grace Hopper"},
        ]
        if snapshot == "users"
        else [],
    )
    monkeypatch.setattr("user_admin_jobs.azure_cache.refresh_directory_users", lambda user_ids: None)
    monkeypatch.setattr("user_admin_jobs.time.sleep", lambda seconds: None)

    job = manager.create_job(
        action_type="disable_sign_in",
        target_user_ids=["user-1", "user-2"],
        params={},
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    manager._process_job(job["job_id"])

    updated = manager.get_job(job["job_id"])
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["success_count"] == 1
    assert updated["failure_count"] == 1
    assert call_count["user-1"] == 2
    assert call_count["user-2"] == 1

    results = manager.get_job_results(job["job_id"])
    assert results[0]["success"] is True
    assert results[1]["success"] is False
    assert "User update failed" in results[1]["error"]

    audit = manager.list_audit(limit=10)
    assert len(audit) == 2
    assert audit[0]["target_user_id"] in {"user-1", "user-2"}
    assert all("TempPass" not in json.dumps(entry) for entry in audit)


def test_postgres_mode_backfills_and_persists_jobs(tmp_path, monkeypatch):
    source_db = tmp_path / "user_admin_jobs.db"
    source_manager = UserAdminJobManager(db_path=str(source_db))

    with source_manager._conn() as conn:
        conn.execute(
            """
            INSERT INTO user_admin_jobs (
                job_id,
                status,
                action_type,
                provider,
                target_user_ids_json,
                params_json,
                requested_by_email,
                requested_by_name,
                requested_at,
                progress_current,
                progress_total,
                progress_message
            )
            VALUES (?, 'completed', ?, ?, ?, ?, ?, ?, ?, 1, 1, 'Done')
            """,
            (
                "job-backfill",
                "disable_sign_in",
                "entra",
                json.dumps(["user-1"]),
                "{}",
                "tech@example.com",
                "Tech User",
                "2026-03-19T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO user_admin_job_results (
                id, job_id, target_user_id, target_display_name, provider,
                success, summary, error, before_summary_json, after_summary_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                7,
                "job-backfill",
                "user-1",
                "Ada Lovelace",
                "entra",
                1,
                "Completed",
                "",
                "{}",
                '{"enabled": false}',
                "2026-03-19T00:01:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO user_admin_audit (
                audit_id, job_id, actor_email, actor_name, target_user_id,
                target_display_name, provider, action_type, params_summary_json,
                before_summary_json, after_summary_json, status, error, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "audit-backfill",
                "job-backfill",
                "tech@example.com",
                "Tech User",
                "user-1",
                "Ada Lovelace",
                "entra",
                "disable_sign_in",
                "{}",
                "{}",
                '{"enabled": false}',
                "success",
                "",
                "2026-03-19T00:02:00+00:00",
            ),
        )
        conn.commit()

    class FakeProviders:
        @staticmethod
        def provider_for_action(action_type):
            assert action_type == "disable_sign_in"
            return _EnabledProvider(), "entra"

    fake_pg = _FakePostgresConnection()
    monkeypatch.setattr(user_admin_jobs_module, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(user_admin_jobs_module, "postgres_enabled", lambda: True)
    monkeypatch.setattr(user_admin_jobs_module, "ensure_postgres_schema", lambda: None)
    monkeypatch.setattr(user_admin_jobs_module, "connect_postgres", lambda: fake_pg)
    monkeypatch.setattr("user_admin_jobs.user_admin_providers", FakeProviders())

    manager = UserAdminJobManager()

    backfilled = manager.get_job("job-backfill")
    assert backfilled is not None
    assert backfilled["status"] == "completed"
    assert backfilled["progress_total"] == 1

    results = manager.get_job_results("job-backfill")
    assert results[0]["summary"] == "Completed"

    audit = manager.list_audit(limit=10)
    assert audit[0]["audit_id"] == "audit-backfill"

    created = manager.create_job(
        action_type="disable_sign_in",
        target_user_ids=["user-2"],
        params={},
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )
    assert created["status"] == "queued"

    row = fake_pg.execute(
        "SELECT requested_by_email, target_user_ids_json FROM user_admin_jobs WHERE job_id = %s",
        (created["job_id"],),
    ).fetchone()
    assert row is not None
    assert row["requested_by_email"] == "tech@example.com"
    assert json.loads(str(row["target_user_ids_json"])) == ["user-2"]
