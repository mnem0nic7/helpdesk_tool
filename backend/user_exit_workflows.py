"""Hybrid user exit workflow orchestration for the primary users workspace."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from azure_cache import azure_cache
from config import DATA_DIR, USER_EXIT_AGENT_STEP_LEASE_SECONDS
from models import UserExitWorkflowStatus
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite
from user_admin_jobs import user_admin_jobs
from user_admin_providers import UserAdminProviderError, user_admin_providers

logger = logging.getLogger(__name__)

_ACTIVE_WORKFLOW_STATUSES = {"queued", "running", "awaiting_manual"}
_STEP_DONE_STATUSES = {"completed", "skipped"}
_LOCAL_STEP_KEYS = {"disable_sign_in", "revoke_sessions", "reset_mfa", "exit_group_cleanup", "exit_remove_all_licenses"}
_AGENT_STEP_KEYS = {"exit_on_prem_deprovision", "mailbox_convert_type"}
_PROFILE_LABELS = {
    "canyon": "Canyon",
    "khm": "KHM",
    "oasis": "Oasis",
}
_STEP_LABELS = {
    "disable_sign_in": "Disable Entra Sign-In",
    "revoke_sessions": "Revoke Sessions",
    "reset_mfa": "Reset MFA Registrations",
    "exit_group_cleanup": "Remove Direct Cloud Group Memberships",
    "exit_on_prem_deprovision": "Run On-Prem AD Deprovisioning",
    "mailbox_convert_type": "Convert Mailbox to Shared",
    "exit_remove_all_licenses": "Remove Direct M365 Licenses",
}
_MANUAL_TASKS = [
    "RingCentral",
    "Building keycard",
    "Adobe Pro review",
    "Microsoft 365 activations review",
    "Device collection",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps(value: Any) -> str:
    return json.dumps(value)


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


class UserExitWorkflowError(RuntimeError):
    """Known exit workflow failure."""


class UserExitWorkflowManager:
    """Postgres-aware orchestrator for primary-site exit workflows."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "user_exit_workflows.db")
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._bg_task: asyncio.Task[None] | None = None
        self._init_db()
        self._requeue_incomplete_state()

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._sqlite_conn()

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sql(self, statement: str) -> str:
        return statement.replace("?", self._placeholder()) if self._use_postgres else statement

    def _backfill_from_sqlite_if_needed(self) -> None:
        if not self._use_postgres or not os.path.exists(self._db_path):
            return
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM user_exit_workflows").fetchone()
            if row and int(row["count"]) > 0:
                return
        with self._sqlite_conn() as sqlite_conn:
            workflow_rows = sqlite_conn.execute("SELECT * FROM user_exit_workflows").fetchall()
            step_rows = sqlite_conn.execute("SELECT * FROM user_exit_steps").fetchall()
            manual_task_rows = sqlite_conn.execute("SELECT * FROM user_exit_manual_tasks").fetchall()
        with self._conn() as conn:
            if workflow_rows:
                conn.executemany(
                    """
                    INSERT INTO user_exit_workflows (
                        workflow_id, user_id, user_display_name, user_principal_name, requested_by_email,
                        requested_by_name, status, profile_key, on_prem_required,
                        requires_on_prem_username_override, on_prem_sam_account_name,
                        on_prem_distinguished_name, created_at, started_at, completed_at, error
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT(workflow_id) DO NOTHING
                    """,
                    [
                        (
                            row["workflow_id"],
                            row["user_id"],
                            row["user_display_name"],
                            row["user_principal_name"],
                            row["requested_by_email"],
                            row["requested_by_name"],
                            row["status"],
                            row["profile_key"],
                            row["on_prem_required"],
                            row["requires_on_prem_username_override"],
                            row["on_prem_sam_account_name"],
                            row["on_prem_distinguished_name"],
                            row["created_at"],
                            row["started_at"],
                            row["completed_at"],
                            row["error"],
                        )
                        for row in workflow_rows
                    ],
                )
            if step_rows:
                conn.executemany(
                    """
                    INSERT INTO user_exit_steps (
                        step_id, workflow_id, step_key, label, provider, status, order_index, profile_key,
                        payload_json, summary, error, before_summary_json, after_summary_json,
                        assigned_agent_id, lease_expires_at, heartbeat_at, created_at, started_at,
                        completed_at, retry_count
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT(step_id) DO NOTHING
                    """,
                    [
                        (
                            row["step_id"],
                            row["workflow_id"],
                            row["step_key"],
                            row["label"],
                            row["provider"],
                            row["status"],
                            row["order_index"],
                            row["profile_key"],
                            row["payload_json"],
                            row["summary"],
                            row["error"],
                            row["before_summary_json"],
                            row["after_summary_json"],
                            row["assigned_agent_id"],
                            row["lease_expires_at"],
                            row["heartbeat_at"],
                            row["created_at"],
                            row["started_at"],
                            row["completed_at"],
                            row["retry_count"],
                        )
                        for row in step_rows
                    ],
                )
            if manual_task_rows:
                conn.executemany(
                    """
                    INSERT INTO user_exit_manual_tasks (
                        task_id, workflow_id, label, status, notes, created_at, completed_at,
                        completed_by_email, completed_by_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(task_id) DO NOTHING
                    """,
                    [
                        (
                            row["task_id"],
                            row["workflow_id"],
                            row["label"],
                            row["status"],
                            row["notes"],
                            row["created_at"],
                            row["completed_at"],
                            row["completed_by_email"],
                            row["completed_by_name"],
                        )
                        for row in manual_task_rows
                    ],
                )

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            self._backfill_from_sqlite_if_needed()
            return
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_exit_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    user_display_name TEXT NOT NULL DEFAULT '',
                    user_principal_name TEXT NOT NULL DEFAULT '',
                    requested_by_email TEXT NOT NULL,
                    requested_by_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    profile_key TEXT NOT NULL DEFAULT '',
                    on_prem_required INTEGER NOT NULL DEFAULT 0,
                    requires_on_prem_username_override INTEGER NOT NULL DEFAULT 0,
                    on_prem_sam_account_name TEXT NOT NULL DEFAULT '',
                    on_prem_distinguished_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_user_exit_workflows_user
                    ON user_exit_workflows (user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS user_exit_steps (
                    step_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    step_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    profile_key TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    summary TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    before_summary_json TEXT NOT NULL DEFAULT '{}',
                    after_summary_json TEXT NOT NULL DEFAULT '{}',
                    assigned_agent_id TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT,
                    heartbeat_at TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_user_exit_steps_workflow
                    ON user_exit_steps (workflow_id, order_index);
                CREATE TABLE IF NOT EXISTS user_exit_manual_tasks (
                    task_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    completed_by_email TEXT NOT NULL DEFAULT '',
                    completed_by_name TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_user_exit_manual_tasks_workflow
                    ON user_exit_manual_tasks (workflow_id, created_at);
                """
            )
            conn.commit()

    def _requeue_incomplete_state(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE user_exit_steps
                SET status = 'queued',
                    assigned_agent_id = '',
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    started_at = NULL,
                    summary = '',
                    error = ''
                WHERE status = 'running'
                """
            )
            conn.execute(
                """
                UPDATE user_exit_workflows
                SET status = 'queued',
                    started_at = NULL,
                    completed_at = NULL,
                    error = ''
                WHERE status IN ('queued', 'running', 'awaiting_manual')
                """
            )
            conn.commit()

    def _lookup_user_row(self, user_id: str) -> dict[str, Any]:
        for item in azure_cache.list_directory_objects("users", search=""):
            if str(item.get("id") or "") == user_id:
                return item
        return {}

    def _profile_key_for_detail(self, detail: dict[str, Any]) -> str:
        on_prem_domain = str(detail.get("on_prem_domain") or "").strip().lower()
        on_prem_netbios = str(detail.get("on_prem_netbios") or "").strip().lower()
        principal_name = str(detail.get("principal_name") or "").strip().lower()
        domain_hint = ""
        if "@" in principal_name:
            domain_hint = principal_name.split("@", 1)[1]
        if "#ext#" in principal_name:
            return ""
        combined = " ".join([on_prem_domain, on_prem_netbios, domain_hint])
        if "canyon" in combined:
            return "canyon"
        if "khm" in combined or "keyhealth" in combined:
            return "khm"
        if (
            "oasis" in combined
            or "movedocs.com" in combined
            or "librasolutionsgroup.com" in combined
            or "grsfunding.com" in combined
            or "probateadvance.com" in combined
            or "relieffunding.com" in combined
        ):
            return "oasis"
        return ""

    def _manual_task_labels(self, detail: dict[str, Any]) -> list[str]:
        labels = list(_MANUAL_TASKS)
        if "business development executive" in str(detail.get("job_title") or "").strip().lower():
            labels.append("Salesforce deactivation email")
        return labels

    def _build_step_blueprint(self, detail: dict[str, Any], mailbox_expected: bool, license_count: int) -> list[dict[str, Any]]:
        profile_key = self._profile_key_for_detail(detail)
        on_prem_required = bool(detail.get("on_prem_sync")) and bool(profile_key)
        on_prem_identifier = str(detail.get("on_prem_sam_account_name") or "").strip()
        steps = [
            {
                "step_key": "disable_sign_in",
                "label": _STEP_LABELS["disable_sign_in"],
                "provider": "entra",
                "will_run": True,
                "reason": "",
                "payload": {},
            },
            {
                "step_key": "revoke_sessions",
                "label": _STEP_LABELS["revoke_sessions"],
                "provider": "entra",
                "will_run": True,
                "reason": "",
                "payload": {},
            },
            {
                "step_key": "reset_mfa",
                "label": _STEP_LABELS["reset_mfa"],
                "provider": "entra",
                "will_run": True,
                "reason": "",
                "payload": {},
            },
            {
                "step_key": "exit_group_cleanup",
                "label": _STEP_LABELS["exit_group_cleanup"],
                "provider": "entra",
                "will_run": True,
                "reason": "",
                "payload": {},
            },
        ]
        if on_prem_required:
            steps.append(
                {
                    "step_key": "exit_on_prem_deprovision",
                    "label": _STEP_LABELS["exit_on_prem_deprovision"],
                    "provider": "windows_agent",
                    "will_run": bool(on_prem_identifier),
                    "reason": "" if on_prem_identifier else "An on-prem username override is required before launch.",
                    "payload": {
                        "profile_key": profile_key,
                        "on_prem_sam_account_name": on_prem_identifier,
                        "on_prem_distinguished_name": str(detail.get("on_prem_distinguished_name") or ""),
                        "user_principal_name": str(detail.get("principal_name") or ""),
                        "display_name": str(detail.get("display_name") or ""),
                    },
                }
            )
        else:
            reason = "The user is cloud-only." if not detail.get("on_prem_sync") else "No supported on-prem profile matched this user."
            steps.append(
                {
                    "step_key": "exit_on_prem_deprovision",
                    "label": _STEP_LABELS["exit_on_prem_deprovision"],
                    "provider": "windows_agent",
                    "will_run": False,
                    "reason": reason,
                    "payload": {"profile_key": profile_key},
                }
            )

        mailbox_reason = ""
        mailbox_will_run = mailbox_expected and bool(profile_key)
        if not mailbox_expected:
            mailbox_reason = "No mailbox was detected."
        elif not profile_key:
            mailbox_reason = "No supported Exchange profile matched this user."
        steps.append(
            {
                "step_key": "mailbox_convert_type",
                "label": _STEP_LABELS["mailbox_convert_type"],
                "provider": "windows_agent",
                "will_run": mailbox_will_run,
                "reason": mailbox_reason,
                "payload": {
                    "profile_key": profile_key,
                    "target_type": "shared",
                    "hide_from_address_lists": True,
                    "mail": str(detail.get("mail") or detail.get("principal_name") or ""),
                    "user_principal_name": str(detail.get("principal_name") or ""),
                    "display_name": str(detail.get("display_name") or ""),
                },
            }
        )
        steps.append(
            {
                "step_key": "exit_remove_all_licenses",
                "label": _STEP_LABELS["exit_remove_all_licenses"],
                "provider": "entra",
                "will_run": license_count > 0,
                "reason": "" if license_count > 0 else "No direct M365 licenses were found.",
                "payload": {},
            }
        )
        return steps

    def _scope_summary(self, detail: dict[str, Any], profile_key: str) -> str:
        if detail.get("on_prem_sync") and profile_key:
            return f"Hybrid exit workflow ({_PROFILE_LABELS.get(profile_key, profile_key.title())})"
        if detail.get("on_prem_sync"):
            return "Hybrid account with no supported on-prem profile match"
        return "Cloud-only exit workflow"

    def _active_workflow_summary_for_user(self, user_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                self._sql(
                    """
                SELECT *
                FROM user_exit_workflows
                WHERE user_id = ?
                  AND status IN ('queued', 'running', 'awaiting_manual')
                ORDER BY created_at DESC
                LIMIT 1
                """
                ),
                (user_id,),
            ).fetchone()
        return self._workflow_summary_row(row)

    def build_preflight(self, user_id: str) -> dict[str, Any]:
        detail = user_admin_providers.get_user_detail(user_id)
        licenses = user_admin_providers.list_licenses(user_id)
        devices = user_admin_providers.list_devices(user_id)
        mailbox = user_admin_providers.get_mailbox(user_id)
        profile_key = self._profile_key_for_detail(detail)
        requires_override = bool(detail.get("on_prem_sync")) and bool(profile_key) and not str(
            detail.get("on_prem_sam_account_name") or ""
        ).strip()
        warnings: list[str] = []
        if bool(detail.get("on_prem_sync")) and not profile_key:
            warnings.append("This synced user did not match a supported on-prem profile, so the on-prem step will be skipped.")
        if requires_override:
            warnings.append("An on-prem username override is required before the workflow can start.")
        if not mailbox.get("primary_address"):
            warnings.append("No mailbox was detected, so mailbox conversion will be skipped.")
        manual_tasks = [self._manual_task_payload(label=label) for label in self._manual_task_labels(detail)]
        step_blueprint = self._build_step_blueprint(detail, bool(mailbox.get("primary_address")), len(licenses))
        return {
            "user_id": user_id,
            "user_display_name": str(detail.get("display_name") or ""),
            "user_principal_name": str(detail.get("principal_name") or ""),
            "profile_key": profile_key,
            "profile_label": _PROFILE_LABELS.get(profile_key, profile_key.title()) if profile_key else "",
            "scope_summary": self._scope_summary(detail, profile_key),
            "on_prem_required": bool(detail.get("on_prem_sync")) and bool(profile_key),
            "requires_on_prem_username_override": requires_override,
            "on_prem_sam_account_name": str(detail.get("on_prem_sam_account_name") or ""),
            "on_prem_distinguished_name": str(detail.get("on_prem_distinguished_name") or ""),
            "mailbox_expected": bool(mailbox.get("primary_address")),
            "direct_license_count": len(licenses),
            "direct_licenses": licenses,
            "managed_devices": devices,
            "manual_tasks": manual_tasks,
            "steps": [
                {
                    "step_key": item["step_key"],
                    "label": item["label"],
                    "provider": item["provider"],
                    "will_run": bool(item["will_run"]),
                    "reason": item["reason"],
                }
                for item in step_blueprint
            ],
            "warnings": warnings,
            "active_workflow": self._active_workflow_summary_for_user(user_id),
        }

    def _workflow_summary_row(self, row: Any | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "workflow_id": str(row["workflow_id"] or ""),
            "user_id": str(row["user_id"] or ""),
            "user_display_name": str(row["user_display_name"] or ""),
            "user_principal_name": str(row["user_principal_name"] or ""),
            "status": str(row["status"] or "queued"),
            "created_at": str(row["created_at"] or ""),
            "started_at": row["started_at"] or None,
            "completed_at": row["completed_at"] or None,
            "profile_key": str(row["profile_key"] or ""),
            "on_prem_required": bool(row["on_prem_required"]),
            "requires_on_prem_username_override": bool(row["requires_on_prem_username_override"]),
            "error": str(row["error"] or ""),
        }

    def _step_row(self, row: Any) -> dict[str, Any]:
        return {
            "step_id": str(row["step_id"] or ""),
            "step_key": str(row["step_key"] or ""),
            "label": str(row["label"] or ""),
            "provider": str(row["provider"] or ""),
            "status": str(row["status"] or "queued"),
            "order_index": int(row["order_index"] or 0),
            "profile_key": str(row["profile_key"] or ""),
            "payload": _json_loads(row["payload_json"], {}),
            "summary": str(row["summary"] or ""),
            "error": str(row["error"] or ""),
            "before_summary": _json_loads(row["before_summary_json"], {}),
            "after_summary": _json_loads(row["after_summary_json"], {}),
            "assigned_agent_id": str(row["assigned_agent_id"] or ""),
            "lease_expires_at": row["lease_expires_at"] or None,
            "heartbeat_at": row["heartbeat_at"] or None,
            "created_at": str(row["created_at"] or ""),
            "started_at": row["started_at"] or None,
            "completed_at": row["completed_at"] or None,
            "retry_count": int(row["retry_count"] or 0),
        }

    def _manual_task_row(self, row: Any) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"] or ""),
            "label": str(row["label"] or ""),
            "status": str(row["status"] or "pending"),
            "notes": str(row["notes"] or ""),
            "completed_at": row["completed_at"] or None,
            "completed_by_email": str(row["completed_by_email"] or ""),
            "completed_by_name": str(row["completed_by_name"] or ""),
        }

    def _manual_task_payload(self, *, label: str) -> dict[str, Any]:
        return {
            "task_id": "",
            "label": label,
            "status": "pending",
            "notes": "",
            "completed_at": None,
            "completed_by_email": "",
            "completed_by_name": "",
        }

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            workflow_row = conn.execute(
                self._sql("SELECT * FROM user_exit_workflows WHERE workflow_id = ?"),
                (workflow_id,),
            ).fetchone()
            if not workflow_row:
                return None
            step_rows = conn.execute(
                self._sql(
                    """
                SELECT *
                FROM user_exit_steps
                WHERE workflow_id = ?
                ORDER BY order_index ASC
                """
                ),
                (workflow_id,),
            ).fetchall()
            task_rows = conn.execute(
                self._sql(
                    """
                SELECT *
                FROM user_exit_manual_tasks
                WHERE workflow_id = ?
                ORDER BY created_at ASC
                """
                ),
                (workflow_id,),
            ).fetchall()
        workflow = dict(self._workflow_summary_row(workflow_row) or {})
        workflow.update(
            {
                "requested_by_email": str(workflow_row["requested_by_email"] or ""),
                "requested_by_name": str(workflow_row["requested_by_name"] or ""),
                "on_prem_sam_account_name": str(workflow_row["on_prem_sam_account_name"] or ""),
                "on_prem_distinguished_name": str(workflow_row["on_prem_distinguished_name"] or ""),
                "steps": [self._step_row(row) for row in step_rows],
                "manual_tasks": [self._manual_task_row(row) for row in task_rows],
            }
        )
        return workflow

    def create_workflow(
        self,
        *,
        user_id: str,
        typed_upn_confirmation: str,
        on_prem_sam_account_name_override: str,
        requested_by_email: str,
        requested_by_name: str,
    ) -> dict[str, Any]:
        preflight = self.build_preflight(user_id)
        if preflight.get("active_workflow"):
            raise UserExitWorkflowError("An active exit workflow already exists for this user")
        expected_upn = str(preflight.get("user_principal_name") or "")
        if typed_upn_confirmation.strip().lower() != expected_upn.strip().lower():
            raise UserExitWorkflowError("The typed UPN confirmation did not match the target user")

        on_prem_override = on_prem_sam_account_name_override.strip()
        if preflight.get("requires_on_prem_username_override") and not on_prem_override:
            raise UserExitWorkflowError("An on-prem username override is required for this workflow")

        workflow_id = uuid.uuid4().hex
        created_at = _utcnow().isoformat()
        steps_blueprint = self._build_step_blueprint(
            {
                **user_admin_providers.get_user_detail(user_id),
                "on_prem_sam_account_name": on_prem_override or str(preflight.get("on_prem_sam_account_name") or ""),
            },
            bool(preflight.get("mailbox_expected")),
            int(preflight.get("direct_license_count") or 0),
        )

        with self._conn() as conn:
            conn.execute(
                self._sql(
                    """
                INSERT INTO user_exit_workflows (
                    workflow_id,
                    user_id,
                    user_display_name,
                    user_principal_name,
                    requested_by_email,
                    requested_by_name,
                    status,
                    profile_key,
                    on_prem_required,
                    requires_on_prem_username_override,
                    on_prem_sam_account_name,
                    on_prem_distinguished_name,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """
                ),
                (
                    workflow_id,
                    user_id,
                    str(preflight.get("user_display_name") or ""),
                    str(preflight.get("user_principal_name") or ""),
                    requested_by_email,
                    requested_by_name,
                    str(preflight.get("profile_key") or ""),
                    1 if preflight.get("on_prem_required") else 0,
                    1 if preflight.get("requires_on_prem_username_override") else 0,
                    on_prem_override or str(preflight.get("on_prem_sam_account_name") or ""),
                    str(preflight.get("on_prem_distinguished_name") or ""),
                    created_at,
                ),
            )
            for order_index, step in enumerate(steps_blueprint, start=1):
                payload = dict(step["payload"])
                if step["step_key"] == "exit_on_prem_deprovision":
                    payload["on_prem_sam_account_name"] = on_prem_override or payload.get("on_prem_sam_account_name") or ""
                conn.execute(
                    self._sql(
                        """
                    INSERT INTO user_exit_steps (
                        step_id,
                        workflow_id,
                        step_key,
                        label,
                        provider,
                        status,
                        order_index,
                        profile_key,
                        payload_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    ),
                    (
                        uuid.uuid4().hex,
                        workflow_id,
                        step["step_key"],
                        step["label"],
                        step["provider"],
                        "queued" if step["will_run"] else "skipped",
                        order_index,
                        str(payload.get("profile_key") or ""),
                        _json_dumps(payload),
                        created_at,
                    ),
                )
            for label in self._manual_task_labels(user_admin_providers.get_user_detail(user_id)):
                conn.execute(
                    self._sql(
                        """
                    INSERT INTO user_exit_manual_tasks (
                        task_id,
                        workflow_id,
                        label,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, 'pending', ?)
                    """
                    ),
                    (
                        uuid.uuid4().hex,
                        workflow_id,
                        label,
                        created_at,
                    ),
                )
            conn.commit()

        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise UserExitWorkflowError("Failed to create the exit workflow")
        return workflow

    def _claim_next_local_step(self) -> dict[str, Any] | None:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    self._sql(
                        """
                    SELECT s.*
                    FROM user_exit_steps s
                    JOIN user_exit_workflows w
                      ON w.workflow_id = s.workflow_id
                    WHERE s.provider = 'entra'
                      AND s.status = 'queued'
                      AND w.status IN ('queued', 'running')
                      AND NOT EXISTS (
                        SELECT 1
                        FROM user_exit_steps prior
                        WHERE prior.workflow_id = s.workflow_id
                          AND prior.order_index < s.order_index
                          AND prior.status NOT IN ('completed', 'skipped')
                    )
                    ORDER BY w.created_at ASC, s.order_index ASC
                    LIMIT 1
                    """
                    )
                ).fetchone()
                if not row:
                    return None
                step_id = str(row["step_id"] or "")
                now = _utcnow().isoformat()
                conn.execute(
                    self._sql(
                        """
                    UPDATE user_exit_steps
                    SET status = 'running',
                        started_at = COALESCE(started_at, ?)
                    WHERE step_id = ?
                    """
                    ),
                    (now, step_id),
                )
                conn.execute(
                    self._sql(
                        """
                    UPDATE user_exit_workflows
                    SET status = 'running',
                        started_at = COALESCE(started_at, ?),
                        error = ''
                    WHERE workflow_id = ?
                    """
                    ),
                    (now, str(row["workflow_id"] or "")),
                )
                conn.commit()
        workflow = self.get_workflow(str(row["workflow_id"] or ""))
        if not workflow:
            return None
        for step in workflow.get("steps") or []:
            if str(step.get("step_id") or "") == str(row["step_id"] or ""):
                return {
                    "workflow": workflow,
                    "step": step,
                }
        return None

    def _record_step_audit(
        self,
        *,
        workflow: dict[str, Any],
        step: dict[str, Any],
        status: str,
        summary: str,
        error: str,
        before_summary: dict[str, Any],
        after_summary: dict[str, Any],
    ) -> None:
        user_admin_jobs.record_audit_entry(
            job_id=str(workflow.get("workflow_id") or ""),
            actor_email=str(workflow.get("requested_by_email") or ""),
            actor_name=str(workflow.get("requested_by_name") or ""),
            target_user_id=str(workflow.get("user_id") or ""),
            target_display_name=str(workflow.get("user_display_name") or ""),
            provider=str(step.get("provider") or "workflow"),
            action_type=str(step.get("step_key") or "exit_manual_task_complete"),
            params=dict(step.get("payload") or {}),
            before_summary=before_summary,
            after_summary=after_summary or {"summary": summary} if summary else after_summary,
            status=status,
            error=error,
        )

    def _refresh_user_cache(self, user_id: str) -> None:
        refresh_users = getattr(azure_cache, "refresh_directory_users", None)
        if callable(refresh_users):
            refresh_users([user_id])
            return
        try:
            azure_cache.refresh_datasets(["directory"], force=True)
        except Exception:
            logger.exception("Failed to refresh Azure directory users after exit workflow step")

    def _sync_workflow_status(self, workflow_id: str) -> None:
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            return
        steps = workflow.get("steps") or []
        manual_tasks = workflow.get("manual_tasks") or []
        failed_steps = [step for step in steps if step.get("status") == "failed"]
        if failed_steps:
            failed_step = failed_steps[0]
            self._update_workflow(
                workflow_id,
                status="failed",
                completed_at=None,
                error=str(failed_step.get("error") or failed_step.get("label") or "Step failed"),
            )
            return
        if not all(step.get("status") in _STEP_DONE_STATUSES for step in steps):
            self._update_workflow(workflow_id, status="running", error="")
            return
        if all(task.get("status") == "completed" for task in manual_tasks):
            self._update_workflow(
                workflow_id,
                status="completed",
                completed_at=_utcnow().isoformat(),
                error="",
            )
            return
        self._update_workflow(workflow_id, status="awaiting_manual", error="")

    def _update_workflow(self, workflow_id: str, **fields: Any) -> None:
        if not fields:
            return
        placeholder = self._placeholder()
        assignments = ", ".join(f"{key} = {placeholder}" for key in fields)
        values = list(fields.values()) + [workflow_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE user_exit_workflows SET {assignments} WHERE workflow_id = {placeholder}", values)
            conn.commit()

    def _update_step(self, step_id: str, **fields: Any) -> None:
        if not fields:
            return
        placeholder = self._placeholder()
        assignments = ", ".join(f"{key} = {placeholder}" for key in fields)
        values = list(fields.values()) + [step_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE user_exit_steps SET {assignments} WHERE step_id = {placeholder}", values)
            conn.commit()

    def _process_local_step(self, workflow: dict[str, Any], step: dict[str, Any]) -> None:
        workflow_id = str(workflow.get("workflow_id") or "")
        user_id = str(workflow.get("user_id") or "")
        step_key = str(step.get("step_key") or "")
        result: dict[str, Any] | None = None
        status = "completed"
        error = ""

        try:
            if step_key == "exit_group_cleanup":
                result = user_admin_providers.entra.remove_direct_cloud_group_memberships(user_id)
            elif step_key == "exit_remove_all_licenses":
                result = user_admin_providers.entra.remove_all_direct_licenses(user_id)
            else:
                result = user_admin_providers.execute(step_key, user_id, dict(step.get("payload") or {}))
        except UserAdminProviderError as exc:
            status = "failed"
            error = str(exc)
        except Exception as exc:
            logger.exception("Exit workflow step %s failed for %s", step_key, user_id)
            status = "failed"
            error = str(exc)

        if status == "completed" and result is not None:
            summary = str(result.get("summary") or "Completed")
            before_summary = dict(result.get("before_summary") or {})
            after_summary = dict(result.get("after_summary") or {})
            self._update_step(
                str(step.get("step_id") or ""),
                status="completed",
                completed_at=_utcnow().isoformat(),
                summary=summary,
                error="",
                before_summary_json=_json_dumps(before_summary),
                after_summary_json=_json_dumps(after_summary),
            )
            self._record_step_audit(
                workflow=workflow,
                step=step,
                status="success",
                summary=summary,
                error="",
                before_summary=before_summary,
                after_summary=after_summary,
            )
            self._refresh_user_cache(user_id)
        else:
            self._update_step(
                str(step.get("step_id") or ""),
                status="failed",
                completed_at=_utcnow().isoformat(),
                summary="Failed",
                error=error,
                before_summary_json=_json_dumps({}),
                after_summary_json=_json_dumps({}),
            )
            self._record_step_audit(
                workflow=workflow,
                step=step,
                status="failed",
                summary="Failed",
                error=error,
                before_summary={},
                after_summary={},
            )

        self._sync_workflow_status(workflow_id)

    def _requeue_expired_agent_steps(self) -> None:
        with self._conn() as conn:
            rows = conn.execute(
                self._sql(
                    """
                SELECT step_id
                FROM user_exit_steps
                WHERE provider = 'windows_agent'
                  AND status = 'running'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?
                """
                ),
                (_utcnow().isoformat(),),
            ).fetchall()
            step_ids = [str(row["step_id"] or "") for row in rows]
            if not step_ids:
                return
            for step_id in step_ids:
                conn.execute(
                    self._sql(
                        """
                    UPDATE user_exit_steps
                    SET status = 'queued',
                        assigned_agent_id = '',
                        lease_expires_at = NULL,
                        heartbeat_at = NULL,
                        summary = '',
                        error = ''
                    WHERE step_id = ?
                    """
                    ),
                    (step_id,),
                )
            conn.commit()
        for step_id in step_ids:
            workflow_id = self._workflow_id_for_step(step_id)
            if workflow_id:
                self._sync_workflow_status(workflow_id)

    def _workflow_id_for_step(self, step_id: str) -> str:
        with self._conn() as conn:
            row = conn.execute(self._sql("SELECT workflow_id FROM user_exit_steps WHERE step_id = ?"), (step_id,)).fetchone()
        return str(row["workflow_id"] or "") if row else ""

    async def start_worker(self) -> None:
        if self._bg_task and not self._bg_task.done():
            return
        self._bg_task = asyncio.get_running_loop().create_task(self._background_loop())

    async def stop_worker(self) -> None:
        if not self._bg_task:
            return
        self._bg_task.cancel()
        try:
            await self._bg_task
        except asyncio.CancelledError:
            pass
        self._bg_task = None

    async def _background_loop(self) -> None:
        while True:
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._requeue_expired_agent_steps)
                next_step = await asyncio.get_running_loop().run_in_executor(None, self._claim_next_local_step)
                if not next_step:
                    await asyncio.sleep(2)
                    continue
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    self._process_local_step,
                    next_step["workflow"],
                    next_step["step"],
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("User exit workflow background loop failed")
                await asyncio.sleep(2)

    def retry_step(self, workflow_id: str, step_id: str) -> dict[str, Any]:
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise UserExitWorkflowError("Workflow not found")
        target = next((item for item in workflow.get("steps") or [] if item.get("step_id") == step_id), None)
        if not target:
            raise UserExitWorkflowError("Step not found")
        if target.get("status") != "failed":
            raise UserExitWorkflowError("Only failed steps can be retried")
        self._update_step(
            step_id,
            status="queued",
            summary="",
            error="",
            before_summary_json=_json_dumps({}),
            after_summary_json=_json_dumps({}),
            assigned_agent_id="",
            lease_expires_at=None,
            heartbeat_at=None,
            completed_at=None,
            retry_count=int(target.get("retry_count") or 0) + 1,
        )
        self._update_workflow(workflow_id, status="running", completed_at=None, error="")
        refreshed = self.get_workflow(workflow_id)
        if not refreshed:
            raise UserExitWorkflowError("Workflow not found after retry")
        return refreshed

    def complete_manual_task(
        self,
        workflow_id: str,
        task_id: str,
        *,
        actor_email: str,
        actor_name: str,
        notes: str = "",
    ) -> dict[str, Any]:
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise UserExitWorkflowError("Workflow not found")
        with self._conn() as conn:
            row = conn.execute(
                self._sql("SELECT * FROM user_exit_manual_tasks WHERE workflow_id = ? AND task_id = ?"),
                (workflow_id, task_id),
            ).fetchone()
            if not row:
                raise UserExitWorkflowError("Manual task not found")
            if str(row["status"] or "") == "completed":
                return workflow
            completed_at = _utcnow().isoformat()
            conn.execute(
                self._sql(
                    """
                UPDATE user_exit_manual_tasks
                SET status = 'completed',
                    notes = ?,
                    completed_at = ?,
                    completed_by_email = ?,
                    completed_by_name = ?
                WHERE task_id = ?
                """
                ),
                (notes, completed_at, actor_email, actor_name, task_id),
            )
            conn.commit()
        task_label = str(row["label"] or "")
        user_admin_jobs.record_audit_entry(
            job_id=workflow_id,
            actor_email=actor_email,
            actor_name=actor_name,
            target_user_id=str(workflow.get("user_id") or ""),
            target_display_name=str(workflow.get("user_display_name") or ""),
            provider="workflow",
            action_type="exit_manual_task_complete",
            params={"task_label": task_label},
            before_summary={"task_status": "pending"},
            after_summary={"task_label": task_label, "task_status": "completed", "notes": notes},
            status="success",
            error="",
        )
        self._sync_workflow_status(workflow_id)
        refreshed = self.get_workflow(workflow_id)
        if not refreshed:
            raise UserExitWorkflowError("Workflow not found after manual completion")
        return refreshed

    def claim_agent_step(self, *, agent_id: str, profile_keys: list[str]) -> dict[str, Any] | None:
        normalized_profiles = [str(item).strip().lower() for item in profile_keys if str(item).strip()]
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    self._sql(
                        """
                    SELECT s.*, w.user_id, w.user_display_name, w.user_principal_name
                    FROM user_exit_steps s
                    JOIN user_exit_workflows w
                      ON w.workflow_id = s.workflow_id
                    WHERE s.provider = 'windows_agent'
                      AND s.status = 'queued'
                      AND w.status IN ('queued', 'running')
                      AND NOT EXISTS (
                        SELECT 1
                        FROM user_exit_steps prior
                        WHERE prior.workflow_id = s.workflow_id
                          AND prior.order_index < s.order_index
                          AND prior.status NOT IN ('completed', 'skipped')
                      )
                    ORDER BY w.created_at ASC, s.order_index ASC
                    """
                    )
                ).fetchall()
                chosen: Any | None = None
                for row in rows:
                    profile_key = str(row["profile_key"] or "").strip().lower()
                    if normalized_profiles and profile_key and profile_key not in normalized_profiles:
                        continue
                    chosen = row
                    break
                if not chosen:
                    return None
                lease_expires_at = (_utcnow() + timedelta(seconds=max(30, USER_EXIT_AGENT_STEP_LEASE_SECONDS))).isoformat()
                now = _utcnow().isoformat()
                conn.execute(
                    self._sql(
                        """
                    UPDATE user_exit_steps
                    SET status = 'running',
                        assigned_agent_id = ?,
                        started_at = COALESCE(started_at, ?),
                        heartbeat_at = ?,
                        lease_expires_at = ?
                    WHERE step_id = ?
                    """
                    ),
                    (agent_id, now, now, lease_expires_at, str(chosen["step_id"] or "")),
                )
                conn.execute(
                    self._sql(
                        """
                    UPDATE user_exit_workflows
                    SET status = 'running',
                        started_at = COALESCE(started_at, ?),
                        error = ''
                    WHERE workflow_id = ?
                    """
                    ),
                    (now, str(chosen["workflow_id"] or "")),
                )
                conn.commit()
        payload = _json_loads(chosen["payload_json"], {})
        return {
            "step_id": str(chosen["step_id"] or ""),
            "workflow_id": str(chosen["workflow_id"] or ""),
            "step_key": str(chosen["step_key"] or ""),
            "label": str(chosen["label"] or ""),
            "profile_key": str(chosen["profile_key"] or ""),
            "user_id": str(chosen["user_id"] or ""),
            "user_display_name": str(chosen["user_display_name"] or ""),
            "user_principal_name": str(chosen["user_principal_name"] or ""),
            "on_prem_sam_account_name": str(payload.get("on_prem_sam_account_name") or ""),
            "on_prem_distinguished_name": str(payload.get("on_prem_distinguished_name") or ""),
            "payload": payload,
            "lease_expires_at": lease_expires_at,
        }

    def heartbeat_agent_step(self, *, step_id: str, agent_id: str) -> None:
        with self._conn() as conn:
            row = conn.execute(
                self._sql("SELECT assigned_agent_id, status FROM user_exit_steps WHERE step_id = ?"),
                (step_id,),
            ).fetchone()
            if not row:
                raise UserExitWorkflowError("Step not found")
            if str(row["status"] or "") != "running" or str(row["assigned_agent_id"] or "") != agent_id:
                raise UserExitWorkflowError("Step is not assigned to this agent")
            now = _utcnow().isoformat()
            lease_expires_at = (_utcnow() + timedelta(seconds=max(30, USER_EXIT_AGENT_STEP_LEASE_SECONDS))).isoformat()
            conn.execute(
                self._sql(
                    """
                UPDATE user_exit_steps
                SET heartbeat_at = ?,
                    lease_expires_at = ?
                WHERE step_id = ?
                """
                ),
                (now, lease_expires_at, step_id),
            )
            conn.commit()

    def complete_agent_step(
        self,
        *,
        step_id: str,
        agent_id: str,
        status: str,
        summary: str,
        error: str,
        before_summary: dict[str, Any],
        after_summary: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = self._workflow_id_for_step(step_id)
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise UserExitWorkflowError("Workflow not found")
        target_step = next((item for item in workflow.get("steps") or [] if item.get("step_id") == step_id), None)
        if not target_step:
            raise UserExitWorkflowError("Step not found")
        if str(target_step.get("assigned_agent_id") or "") != agent_id:
            raise UserExitWorkflowError("Step is not assigned to this agent")
        if status not in {"completed", "failed", "skipped"}:
            raise UserExitWorkflowError("Unsupported agent step status")
        self._update_step(
            step_id,
            status=status,
            summary=summary or ("Completed" if status == "completed" else "Skipped" if status == "skipped" else "Failed"),
            error=error,
            before_summary_json=_json_dumps(before_summary),
            after_summary_json=_json_dumps(after_summary),
            completed_at=_utcnow().isoformat(),
            heartbeat_at=None,
            lease_expires_at=None,
        )
        audit_status = "success" if status in {"completed", "skipped"} else "failed"
        self._record_step_audit(
            workflow=workflow,
            step=target_step,
            status=audit_status if status != "skipped" else "skipped",
            summary=summary,
            error=error,
            before_summary=before_summary,
            after_summary=after_summary,
        )
        if status == "completed":
            self._refresh_user_cache(str(workflow.get("user_id") or ""))
        self._sync_workflow_status(workflow_id)
        refreshed = self.get_workflow(workflow_id)
        if not refreshed:
            raise UserExitWorkflowError("Workflow not found after step completion")
        return refreshed


user_exit_workflows = UserExitWorkflowManager()
