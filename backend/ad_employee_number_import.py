"""AD employee-number bulk import: CSV parsing, row classification, job store, and
background match/apply phases for the Tools-page admin tool."""
from __future__ import annotations

import csv
import io
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

EMAIL_COLUMN = "emails_work_value"
EMPLOYEE_NUMBER_COLUMN = "ENT_employeeNumber"

RowAction = str  # "update" | "no_change" | "not_found" | "skipped_blank" | "skipped_duplicate"

_DB_PATH = os.path.join(DATA_DIR, "ad_employee_number_import.db")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_csv_rows(csv_bytes: bytes) -> list[dict[str, str]]:
    """Parse CSV bytes into a list of row dicts using the stdlib csv module.

    Raises ValueError if the required columns are missing from the header.
    """
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    if EMAIL_COLUMN not in fieldnames:
        raise ValueError(f"CSV is missing the required '{EMAIL_COLUMN}' column")
    if EMPLOYEE_NUMBER_COLUMN not in fieldnames:
        raise ValueError(f"CSV is missing the required '{EMPLOYEE_NUMBER_COLUMN}' column")
    return [dict(row) for row in reader]


def build_row_plan(
    rows: list[dict[str, str]],
    *,
    ad_lookup: Callable[[str], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """Classify each CSV row against Active Directory.

    Dedupes by email, keeping the *last* occurrence of a non-blank email/value
    pair in file order; earlier duplicates are tagged 'skipped_duplicate'.
    Rows with a blank employee-number value are tagged 'skipped_blank' and
    never trigger an AD lookup (never clears AD). Rows with a blank email, or
    an email with no AD match, are tagged 'not_found'.
    """
    # Find the last row index for each non-blank email so earlier repeats
    # (that would otherwise be actionable) can be superseded.
    last_index_for_email: dict[str, int] = {}
    for index, row in enumerate(rows):
        email = (row.get(EMAIL_COLUMN) or "").strip()
        if email:
            last_index_for_email[email] = index

    plan: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        email = (row.get(EMAIL_COLUMN) or "").strip()
        new_value = (row.get(EMPLOYEE_NUMBER_COLUMN) or "").strip()

        result: dict[str, Any] = {
            "row_index": index,
            "source_email": email,
            "ad_sam": "",
            "ad_display_name": "",
            "current_employee_number": "",
            "new_employee_number": new_value,
            "action": "",
        }

        if not new_value:
            result["action"] = "skipped_blank"
        elif email and last_index_for_email.get(email) != index:
            result["action"] = "skipped_duplicate"
        elif not email:
            result["action"] = "not_found"
        else:
            ad_user = ad_lookup(email)
            if ad_user is None:
                result["action"] = "not_found"
            else:
                result["ad_sam"] = str(ad_user.get("sam_account_name") or "")
                result["ad_display_name"] = str(ad_user.get("display_name") or "")
                current_value = str(ad_user.get("employee_number") or "")
                result["current_employee_number"] = current_value
                result["action"] = "no_change" if current_value == new_value else "update"

        plan.append(result)

    return plan


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_JOB_COLUMNS = [
    "job_id", "requested_by", "filename", "status", "total_rows",
    "update_count", "no_change_count", "not_found_count", "skipped_count",
    "applied_count", "apply_failed_count", "error",
    "created_at", "updated_at", "completed_at",
]

_ROW_COLUMNS = [
    "id", "job_id", "row_index", "source_email", "ad_sam", "ad_display_name",
    "current_employee_number", "new_employee_number", "action", "applied", "apply_error",
]


class AdEmployeeNumberImportStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

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
                CREATE TABLE IF NOT EXISTS ad_employee_number_import_jobs (
                    job_id              TEXT PRIMARY KEY,
                    requested_by       TEXT NOT NULL DEFAULT '',
                    filename            TEXT NOT NULL DEFAULT '',
                    status              TEXT NOT NULL DEFAULT 'queued',
                    total_rows          INTEGER NOT NULL DEFAULT 0,
                    update_count        INTEGER NOT NULL DEFAULT 0,
                    no_change_count     INTEGER NOT NULL DEFAULT 0,
                    not_found_count     INTEGER NOT NULL DEFAULT 0,
                    skipped_count       INTEGER NOT NULL DEFAULT 0,
                    applied_count       INTEGER NOT NULL DEFAULT 0,
                    apply_failed_count  INTEGER NOT NULL DEFAULT 0,
                    error               TEXT NOT NULL DEFAULT '',
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL,
                    completed_at        TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_employee_number_import_rows (
                    id                       TEXT PRIMARY KEY,
                    job_id                   TEXT NOT NULL,
                    row_index                INTEGER NOT NULL,
                    source_email             TEXT NOT NULL DEFAULT '',
                    ad_sam                   TEXT NOT NULL DEFAULT '',
                    ad_display_name          TEXT NOT NULL DEFAULT '',
                    current_employee_number  TEXT NOT NULL DEFAULT '',
                    new_employee_number      TEXT NOT NULL DEFAULT '',
                    action                   TEXT NOT NULL DEFAULT '',
                    applied                  SMALLINT NOT NULL DEFAULT 0,
                    apply_error              TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ad_emp_num_jobs_created "
                "ON ad_employee_number_import_jobs (created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ad_emp_num_rows_job_action "
                "ON ad_employee_number_import_rows (job_id, action)"
            )

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def create_job(self, *, job_id: str, requested_by: str, filename: str, total_rows: int) -> None:
        ph = self._placeholder()
        now = _utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO ad_employee_number_import_jobs
                    (job_id, requested_by, filename, status, total_rows, created_at, updated_at)
                VALUES ({ph},{ph},{ph},'queued',{ph},{ph},{ph})
                """,
                (job_id, requested_by, filename, total_rows, now, now),
            )

    def update_job_status(self, job_id: str, *, status: str, error: str = "") -> None:
        ph = self._placeholder()
        now = _utcnow().isoformat()
        completed_at = now if status in {"completed", "completed_with_errors", "failed", "cancelled"} else None
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE ad_employee_number_import_jobs
                SET status={ph}, error={ph}, updated_at={ph}, completed_at=COALESCE({ph}, completed_at)
                WHERE job_id={ph}
                """,
                (status, error, now, completed_at, job_id),
            )

    def set_job_counts(
        self,
        job_id: str,
        *,
        update_count: int = 0,
        no_change_count: int = 0,
        not_found_count: int = 0,
        skipped_count: int = 0,
        applied_count: int | None = None,
        apply_failed_count: int | None = None,
    ) -> None:
        ph = self._placeholder()
        now = _utcnow().isoformat()
        job = self.get_job(job_id) or {}
        applied_count = job.get("applied_count", 0) if applied_count is None else applied_count
        apply_failed_count = job.get("apply_failed_count", 0) if apply_failed_count is None else apply_failed_count
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE ad_employee_number_import_jobs
                SET update_count={ph}, no_change_count={ph}, not_found_count={ph},
                    skipped_count={ph}, applied_count={ph}, apply_failed_count={ph}, updated_at={ph}
                WHERE job_id={ph}
                """,
                (
                    update_count, no_change_count, not_found_count, skipped_count,
                    applied_count, apply_failed_count, now, job_id,
                ),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM ad_employee_number_import_jobs WHERE job_id = {ph}", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return _job_row_to_dict(row)

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        ph = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM ad_employee_number_import_jobs ORDER BY created_at DESC LIMIT {ph}",
                (limit,),
            ).fetchall()
        return [_job_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Rows
    # ------------------------------------------------------------------

    def insert_rows(self, job_id: str, rows: list[dict[str, Any]]) -> list[str]:
        ph = self._placeholder()
        row_ids: list[str] = []
        with self._conn() as conn:
            for row in rows:
                row_id = uuid.uuid4().hex
                row_ids.append(row_id)
                conn.execute(
                    f"""
                    INSERT INTO ad_employee_number_import_rows
                        (id, job_id, row_index, source_email, ad_sam, ad_display_name,
                         current_employee_number, new_employee_number, action, applied, apply_error)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},0,'')
                    """,
                    (
                        row_id, job_id, row["row_index"], row.get("source_email", ""),
                        row.get("ad_sam", ""), row.get("ad_display_name", ""),
                        row.get("current_employee_number", ""), row.get("new_employee_number", ""),
                        row.get("action", ""),
                    ),
                )
        return row_ids

    def list_rows(
        self, job_id: str, *, action: str | None = None, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        ph = self._placeholder()
        query = f"SELECT * FROM ad_employee_number_import_rows WHERE job_id = {ph}"
        params: list[Any] = [job_id]
        if action:
            query += f" AND action = {ph}"
            params.append(action)
        query += f" ORDER BY row_index LIMIT {ph} OFFSET {ph}"
        params += [limit, offset]
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_row_to_dict(r) for r in rows]

    def count_rows(self, job_id: str, *, action: str | None = None) -> int:
        ph = self._placeholder()
        query = f"SELECT COUNT(*) AS n FROM ad_employee_number_import_rows WHERE job_id = {ph}"
        params: list[Any] = [job_id]
        if action:
            query += f" AND action = {ph}"
            params.append(action)
        with self._conn() as conn:
            row = conn.execute(query, params).fetchone()
        if row is None:
            return 0
        return int(row["n"] if hasattr(row, "keys") else row[0])

    def set_apply_counts(self, job_id: str, *, applied_count: int, apply_failed_count: int) -> None:
        """Update only the apply-phase counts, leaving matching-phase counts untouched."""
        ph = self._placeholder()
        now = _utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE ad_employee_number_import_jobs
                SET applied_count={ph}, apply_failed_count={ph}, updated_at={ph}
                WHERE job_id={ph}
                """,
                (applied_count, apply_failed_count, now, job_id),
            )

    def get_row(self, row_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM ad_employee_number_import_rows WHERE id = {ph}", (row_id,)
            ).fetchone()
        if row is None:
            return None
        return _row_row_to_dict(row)

    def mark_row_applied(self, row_id: str, *, applied: bool, apply_error: str = "") -> None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE ad_employee_number_import_rows SET applied={ph}, apply_error={ph} WHERE id={ph}",
                (1 if applied else 0, apply_error, row_id),
            )

    def render_csv(self, job_id: str) -> str:
        """Render every row for a job as CSV, for the audit-export endpoint."""
        job = self.get_job(job_id)
        if job is None:
            return ""
        rows = self.list_rows(job_id, limit=1_000_000, offset=0)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "row_index", "source_email", "ad_sam", "ad_display_name",
            "current_employee_number", "new_employee_number", "action",
            "applied", "apply_error",
        ])
        for row in rows:
            writer.writerow([
                row["row_index"], row["source_email"], row["ad_sam"], row["ad_display_name"],
                row["current_employee_number"], row["new_employee_number"], row["action"],
                row["applied"], row["apply_error"],
            ])
        return buf.getvalue()


# ------------------------------------------------------------------
# Row helpers
# ------------------------------------------------------------------

def _job_row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row) if hasattr(row, "keys") else {c: row[i] for i, c in enumerate(_JOB_COLUMNS)}
    return d


def _row_row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row) if hasattr(row, "keys") else {c: row[i] for i, c in enumerate(_ROW_COLUMNS)}
    d["applied"] = bool(d.get("applied"))
    return d


# ------------------------------------------------------------------
# Background phases
# ------------------------------------------------------------------

def _count_actions(plan: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "update_count": 0,
        "no_change_count": 0,
        "not_found_count": 0,
        "skipped_count": 0,
    }
    for row in plan:
        action = row["action"]
        if action == "update":
            counts["update_count"] += 1
        elif action == "no_change":
            counts["no_change_count"] += 1
        elif action == "not_found":
            counts["not_found_count"] += 1
        elif action in ("skipped_blank", "skipped_duplicate"):
            counts["skipped_count"] += 1
    return counts


def run_matching_phase(job_id: str, csv_bytes: bytes, *, store: AdEmployeeNumberImportStore) -> None:
    """Parse the CSV, classify every row against AD, and persist the plan.

    Called as a FastAPI BackgroundTask. Moves the job to 'awaiting_confirmation'
    on success, or 'failed' (with the error message) on any hard error — e.g. a
    missing required CSV column or an unreachable AD server.
    """
    import ad_client as ad  # Lazy import so tests can patch sys.modules

    try:
        store.update_job_status(job_id, status="matching")
        csv_rows = parse_csv_rows(csv_bytes)
        plan = build_row_plan(csv_rows, ad_lookup=ad.find_user_by_upn_or_email)
        store.insert_rows(job_id, plan)
        store.set_job_counts(job_id, **_count_actions(plan))
        store.update_job_status(job_id, status="awaiting_confirmation")
    except Exception as exc:
        logger.error("AD employee-number import %s matching phase failed: %s", job_id, exc)
        store.update_job_status(job_id, status="failed", error=str(exc))


def run_apply_phase(
    job_id: str, excluded_row_ids: list[str], *, store: AdEmployeeNumberImportStore
) -> None:
    """Write employeeNumber for every 'update' row not opted out by the admin.

    Called as a FastAPI BackgroundTask, triggered by the confirm route. Moves
    the job to 'completed' or 'completed_with_errors' depending on whether any
    individual row write failed; a hard error (e.g. store I/O failure) marks
    the whole job 'failed'.
    """
    import ad_client as ad  # Lazy import so tests can patch sys.modules

    try:
        store.update_job_status(job_id, status="applying")
        excluded = set(excluded_row_ids)
        rows = store.list_rows(job_id, action="update", limit=1_000_000, offset=0)
        applied_count = 0
        failed_count = 0
        for row in rows:
            if row["id"] in excluded:
                continue
            try:
                ad.update_user(row["ad_sam"], {"employeeNumber": row["new_employee_number"]})
                store.mark_row_applied(row["id"], applied=True, apply_error="")
                applied_count += 1
            except Exception as exc:
                store.mark_row_applied(row["id"], applied=False, apply_error=str(exc))
                failed_count += 1
        store.set_apply_counts(job_id, applied_count=applied_count, apply_failed_count=failed_count)
        store.update_job_status(
            job_id, status="completed_with_errors" if failed_count else "completed"
        )
    except Exception as exc:
        logger.error("AD employee-number import %s apply phase failed: %s", job_id, exc)
        store.update_job_status(job_id, status="failed", error=str(exc))


# ------------------------------------------------------------------
# Module-level store instance
# ------------------------------------------------------------------

ad_employee_number_import_jobs = AdEmployeeNumberImportStore()
