"""Offboarding run lifecycle, lane orchestration, store I/O, and CSV renderer."""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(DATA_DIR, "offboarding_runs.db")

OffboardingLane = Literal[
    "entra_disable",
    "entra_revoke",
    "entra_reset_pw",
    "entra_group_cleanup",
    "entra_group_validate",
    "entra_license_cleanup",
    "ad_disable",
    "ad_reset_pw",
    "ad_group_cleanup",
    "ad_attribute_cleanup",
    "ad_move_ou",
]

# Canonical execution order — subset of lanes submitted by caller are run in this order
_LANE_ORDER: list[str] = [
    "entra_disable",
    "entra_revoke",
    "entra_reset_pw",
    "entra_group_cleanup",
    "entra_group_validate",
    "entra_license_cleanup",
    "ad_disable",
    "ad_reset_pw",
    "ad_group_cleanup",
    "ad_attribute_cleanup",
    "ad_move_ou",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OffboardingRunsStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _conn(self) -> sqlite3.Connection:
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return connect_sqlite(self._db_path)

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS offboarding_runs (
                    run_id          TEXT PRIMARY KEY,
                    entra_user_id   TEXT NOT NULL DEFAULT '',
                    ad_sam          TEXT NOT NULL DEFAULT '',
                    display_name    TEXT NOT NULL DEFAULT '',
                    actor_email     TEXT NOT NULL DEFAULT '',
                    lanes_requested TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'queued',
                    has_errors      SMALLINT NOT NULL DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    started_at      TEXT,
                    finished_at     TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS offboarding_run_steps (
                    step_id     TEXT PRIMARY KEY,
                    run_id      TEXT NOT NULL,
                    lane        TEXT NOT NULL,
                    sequence    INTEGER NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'queued',
                    message     TEXT NOT NULL DEFAULT '',
                    detail_json TEXT,
                    started_at  TEXT,
                    finished_at TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_offboarding_runs_created "
                "ON offboarding_runs (created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_offboarding_run_steps_run "
                "ON offboarding_run_steps (run_id, sequence)"
            )

    # ------------------------------------------------------------------
    # Run CRUD
    # ------------------------------------------------------------------

    def create_run(
        self,
        *,
        run_id: str,
        entra_user_id: str,
        ad_sam: str,
        display_name: str,
        actor_email: str,
        lanes: list[str],
    ) -> None:
        """Insert a new offboarding_runs row with status='queued'."""
        ph = self._placeholder()
        now = _utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO offboarding_runs
                    (run_id, entra_user_id, ad_sam, display_name, actor_email,
                     lanes_requested, status, has_errors, created_at)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},'queued',0,{ph})
                """,
                (
                    run_id,
                    entra_user_id,
                    ad_sam,
                    display_name,
                    actor_email,
                    json.dumps(lanes),
                    now,
                ),
            )

    def start_run(self, run_id: str) -> None:
        """Update status='running' and started_at=now."""
        ph = self._placeholder()
        now = _utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE offboarding_runs SET status='running', started_at={ph} WHERE run_id={ph}",
                (now, run_id),
            )

    def finish_run(self, run_id: str, has_errors: bool) -> None:
        """Update status and finished_at=now.

        Uses 'completed_with_errors' if has_errors else 'completed'.
        """
        ph = self._placeholder()
        now = _utcnow().isoformat()
        status = "completed_with_errors" if has_errors else "completed"
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE offboarding_runs
                SET status={ph}, has_errors={ph}, finished_at={ph}
                WHERE run_id={ph}
                """,
                (status, 1 if has_errors else 0, now, run_id),
            )

    def append_step(self, *, run_id: str, lane: str, sequence: int) -> str:
        """Insert a step row with status='queued'. Returns step_id."""
        step_id = uuid.uuid4().hex
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO offboarding_run_steps
                    (step_id, run_id, lane, sequence, status, message)
                VALUES ({ph},{ph},{ph},{ph},'queued','')
                """,
                (step_id, run_id, lane, sequence),
            )
        return step_id

    def update_step(
        self,
        *,
        step_id: str,
        status: str,
        message: str,
        detail: dict[str, Any] | None,
        started_at: str,
        finished_at: str,
    ) -> None:
        """Update a step row with final status and timing."""
        ph = self._placeholder()
        detail_json = json.dumps(detail) if detail is not None else None
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE offboarding_run_steps
                SET status={ph}, message={ph}, detail_json={ph},
                    started_at={ph}, finished_at={ph}
                WHERE step_id={ph}
                """,
                (status, message, detail_json, started_at, finished_at, step_id),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return run dict with 'steps' list, or None if not found."""
        ph = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM offboarding_runs WHERE run_id = {ph}", (run_id,)
            ).fetchone()
            if row is None:
                return None
            run = _run_row_to_dict(row)
            step_rows = conn.execute(
                f"SELECT * FROM offboarding_run_steps WHERE run_id = {ph} ORDER BY sequence",
                (run_id,),
            ).fetchall()
        run["steps"] = [_step_row_to_dict(r) for r in step_rows]
        return run

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent runs (no steps) ordered by created_at DESC."""
        ph = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM offboarding_runs ORDER BY created_at DESC LIMIT {ph}",
                (limit,),
            ).fetchall()
        return [_run_row_to_dict(r) for r in rows]

    def render_csv(self, run_id: str) -> str:
        """Render a per-run CSV matching the PS1 GroupRemovalReport.csv shape.

        Columns: run_id, display_name, lane, status, started_at, finished_at, message, detail
        """
        run = self.get_run(run_id)
        if run is None:
            return ""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["run_id", "display_name", "lane", "status", "started_at", "finished_at", "message", "detail"])
        display_name = run.get("display_name", "")
        for step in run.get("steps", []):
            detail = step.get("detail")
            detail_str = json.dumps(detail) if detail is not None else ""
            writer.writerow([
                run_id,
                display_name,
                step.get("lane", ""),
                step.get("status", ""),
                step.get("started_at", ""),
                step.get("finished_at", ""),
                step.get("message", ""),
                detail_str,
            ])
        return buf.getvalue()


# ------------------------------------------------------------------
# Row helpers
# ------------------------------------------------------------------

def _run_row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        d = dict(row)
    else:
        cols = [
            "run_id", "entra_user_id", "ad_sam", "display_name", "actor_email",
            "lanes_requested", "status", "has_errors", "created_at", "started_at",
            "finished_at",
        ]
        d = {c: row[c] for c in cols if c in row.keys()}
    # Decode JSON lanes
    lanes_raw = d.get("lanes_requested") or "[]"
    try:
        d["lanes_requested"] = json.loads(lanes_raw)
    except Exception:
        d["lanes_requested"] = []
    # Normalize has_errors to bool
    d["has_errors"] = bool(d.get("has_errors"))
    return d


def _step_row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        d = dict(row)
    else:
        cols = [
            "step_id", "run_id", "lane", "sequence", "status",
            "message", "detail_json", "started_at", "finished_at",
        ]
        d = {c: row[c] for c in cols if c in row.keys()}
    # Decode JSON detail
    detail_raw = d.pop("detail_json", None)
    if detail_raw:
        try:
            d["detail"] = json.loads(detail_raw)
        except Exception:
            d["detail"] = None
    else:
        d["detail"] = None
    return d


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------

def run_offboarding(
    *,
    run_id: str,
    entra_user_id: str,
    ad_sam: str,
    display_name: str,
    lanes: list[str],
    store: OffboardingRunsStore,
) -> None:
    """Execute offboarding lanes sequentially. Called as a BackgroundTask."""
    # Lazy imports to avoid circular dependencies at module load time
    import user_admin_providers as _uap_module
    import ad_client as ad

    _uap = _uap_module.user_admin_providers

    try:
        store.start_run(run_id)
        ordered_lanes = [l for l in _LANE_ORDER if l in set(lanes)]
        has_errors = False
        removed_cloud_groups: list[str] = []  # passed entra_group_cleanup → entra_group_validate

        for seq, lane in enumerate(ordered_lanes):
            step_id = store.append_step(run_id=run_id, lane=lane, sequence=seq)
            started = _utcnow()
            ok = True
            message = ""
            detail: dict[str, Any] | None = None

            try:
                if lane == "entra_disable":
                    result = _uap.entra.execute("disable_sign_in", entra_user_id, {})
                    message = result.get("summary", "Sign-in disabled")
                    detail = result.get("after_summary")

                elif lane == "entra_revoke":
                    result = _uap.entra.execute("revoke_sessions", entra_user_id, {})
                    message = result.get("summary", "Sessions revoked")

                elif lane == "entra_reset_pw":
                    result = _uap.entra.execute("reset_password", entra_user_id, {"force_change_on_next_login": False})
                    message = result.get("summary", "Password reset")

                elif lane == "entra_group_cleanup":
                    result = _uap.entra.remove_direct_cloud_group_memberships(entra_user_id)
                    removed_cloud_groups = result.get("after_summary", {}).get("removed_groups", [])
                    message = result.get("summary", f"Removed {len(removed_cloud_groups)} group(s)")
                    detail = result.get("after_summary")

                elif lane == "entra_group_validate":
                    # Validate by re-fetching current memberships and checking removed groups are gone
                    current_groups = _uap.entra.list_groups(entra_user_id)
                    current_names = {g.get("display_name", "") for g in current_groups}
                    still_present = [g for g in removed_cloud_groups if g in current_names]
                    still_present_count = len(still_present)
                    ok = still_present_count == 0
                    if not ok:
                        has_errors = True  # validation failure — error but don't stop
                        message = f"{still_present_count} group(s) still present"
                    else:
                        message = "All cloud group removals confirmed"
                    detail = {
                        "ok": ok,
                        "still_present": still_present,
                        "still_present_count": still_present_count,
                        "checked_groups": removed_cloud_groups,
                    }

                elif lane == "entra_license_cleanup":
                    result = _uap.entra.remove_all_direct_licenses(entra_user_id)
                    message = result.get("summary", "Licenses removed")
                    detail = result.get("after_summary")

                elif lane == "ad_disable":
                    ad.disable_user(ad_sam)
                    message = "AD account disabled"

                elif lane == "ad_reset_pw":
                    ad.reset_password_random(ad_sam)  # return value (password) intentionally discarded
                    message = "AD password reset"

                elif lane == "ad_group_cleanup":
                    result = ad.remove_from_all_groups_except_domain_users(ad_sam)
                    removed = result.get("removed", [])
                    failures = result.get("failures", [])
                    message = f"Removed {len(removed)} group(s)"
                    if failures:
                        message += f"; {len(failures)} failure(s)"
                        ok = False
                        has_errors = True
                    detail = result

                elif lane == "ad_attribute_cleanup":
                    result = ad.update_termination_attributes(ad_sam)
                    message = "Termination attributes applied"
                    detail = result

                elif lane == "ad_move_ou":
                    new_dn = ad.move_to_disabled_users_ou(ad_sam)
                    message = "Moved to disabled OU"
                    detail = {"new_dn": new_dn}

            except Exception as exc:
                ok = False
                has_errors = True
                message = str(exc)
                logger.error("Offboarding run %s lane %s failed: %s", run_id, lane, exc)

            store.update_step(
                step_id=step_id,
                status="ok" if ok else "failed",
                message=message,
                detail=detail,
                started_at=started.isoformat(),
                finished_at=_utcnow().isoformat(),
            )

        store.finish_run(run_id, has_errors)

    except Exception as exc:
        logger.error("Offboarding run %s fatal error: %s", run_id, exc)
        try:
            store.finish_run(run_id, has_errors=True)
        except Exception:
            pass


# ------------------------------------------------------------------
# Module-level store instance
# ------------------------------------------------------------------

offboarding_runs = OffboardingRunsStore()
