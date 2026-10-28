"""Pull Entra user attributes into newly created HR-board Jira tickets (HRD, LIBTA).

Trigger #1 is "ticket created": ``run_cycle`` discovers recently created tickets, then for each
one looks the employee up in Entra by the work/personal email on the ticket and writes the mapped
fields (``hr_entra_field_map``). Entra always overwrites existing Jira values. A ticket with no
Entra match is retried for ``HR_ENTRA_SYNC_RETRY_MINUTES`` and then gets one internal-only note.

``sync_issue`` is trigger-agnostic so later triggers (status change, schedule, manual) can reuse it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

import hr_entra_field_map as fmap
import hr_trimed_sheet
from azure_client import AzureApiError
from config import (
    DATA_DIR,
    HR_ENTRA_SYNC_ENABLED,
    HR_ENTRA_SYNC_LOOKBACK_MINUTES,
    HR_ENTRA_SYNC_POLL_SECONDS,
    HR_ENTRA_SYNC_PROJECTS,
    HR_ENTRA_SYNC_RETRY_MINUTES,
)
from jira_client import JiraClient
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_SYNCED = "synced"
STATUS_NOT_FOUND = "not_found"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_FAILED = "failed"

_DB_PATH = os.path.join(DATA_DIR, "hr_entra_sync.db")
_DOMAINS_TTL_SECONDS = 3600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class HrEntraSyncJob:
    def __init__(self, db_path: str | None = None, *, jira: Any = None, azure: Any = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        self._jira = jira
        self._azure = azure
        self._bg_task: asyncio.Task[None] | None = None
        self._domains: frozenset[str] = frozenset()
        self._domains_at = 0.0
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------ plumbing

    def _ph(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return connect_sqlite(self._db_path)

    def _jira_client(self) -> Any:
        if self._jira is None:
            self._jira = JiraClient()
        return self._jira

    def _azure_client(self) -> Any:
        if self._azure is not None:
            return self._azure
        import azure_cache

        return azure_cache.azure_cache._client

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS hr_entra_sync_issues (
                    issue_key        TEXT PRIMARY KEY,
                    project_key      TEXT NOT NULL DEFAULT '',
                    status           TEXT NOT NULL DEFAULT 'pending',
                    first_seen_at    TEXT NOT NULL,
                    last_attempt_at  TEXT NOT NULL DEFAULT '',
                    attempts         INTEGER NOT NULL DEFAULT 0,
                    completed_at     TEXT NOT NULL DEFAULT '',
                    matched_upn      TEXT NOT NULL DEFAULT '',
                    matched_via      TEXT NOT NULL DEFAULT '',
                    fields_written   TEXT NOT NULL DEFAULT '[]',
                    fields_skipped   TEXT NOT NULL DEFAULT '{}',
                    error            TEXT NOT NULL DEFAULT '',
                    lookup_fingerprint TEXT NOT NULL DEFAULT '',
                    email_source     TEXT NOT NULL DEFAULT ''
                )"""
            )
            for column in ("lookup_fingerprint", "email_source"):  # DBs created before the re-sync trigger
                try:
                    conn.execute(f"ALTER TABLE hr_entra_sync_issues ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
                except sqlite3.OperationalError:
                    pass

    # ------------------------------------------------------------------ store

    def _register(self, issue_key: str, project_key: str, now: datetime) -> bool:
        ph = self._ph()
        with self._conn() as conn:
            cur = conn.execute(
                f"""INSERT INTO hr_entra_sync_issues (issue_key, project_key, status, first_seen_at)
                    VALUES ({ph},{ph},{ph},{ph}) ON CONFLICT (issue_key) DO NOTHING""",
                (issue_key, project_key, STATUS_PENDING, now.isoformat()),
            )
            return bool(cur.rowcount)

    def get_row(self, issue_key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM hr_entra_sync_issues WHERE issue_key = {self._ph()}", (issue_key,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_rows(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM hr_entra_sync_issues"
        args: tuple[Any, ...] = ()
        if status:
            sql += f" WHERE status = {self._ph()}"
            args = (status,)
        sql += f" ORDER BY first_seen_at DESC LIMIT {int(limit)}"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def summary(self) -> dict[str, Any]:
        """Ticket counts by status and the most recent activity timestamp, for the status page."""
        with self._conn() as conn:
            counts = {
                r["status"]: int(r["cnt"])
                for r in conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM hr_entra_sync_issues GROUP BY status"
                ).fetchall()
            }
            ts = conn.execute(
                "SELECT MAX(last_attempt_at) AS a, MAX(completed_at) AS c, MAX(first_seen_at) AS f "
                "FROM hr_entra_sync_issues"
            ).fetchone()
        last_activity = max((ts["a"] or "", ts["c"] or "", ts["f"] or "")) or None
        return {
            "counts": {k: counts.get(k, 0) for k in (
                STATUS_PENDING, STATUS_SYNCED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS, STATUS_FAILED)},
            "total": sum(counts.values()),
            "last_activity_at": last_activity,
        }

    def _record_attempt(
        self, issue_key: str, now: datetime, error: str = "", fingerprint: str | None = None
    ) -> None:
        ph = self._ph()
        with self._conn() as conn:
            conn.execute(
                f"""UPDATE hr_entra_sync_issues
                    SET attempts = attempts + 1, last_attempt_at = {ph}, error = {ph},
                        lookup_fingerprint = COALESCE({ph}, lookup_fingerprint)
                    WHERE issue_key = {ph} AND status = {ph}""",
                (now.isoformat(), error[:1000], fingerprint, issue_key, STATUS_PENDING),
            )

    def _reopen(self, issue_key: str, fingerprint: str, now: datetime) -> bool:
        """Send a finished ticket back through the pipeline because its lookup email changed."""
        ph = self._ph()
        with self._conn() as conn:
            cur = conn.execute(
                f"""UPDATE hr_entra_sync_issues
                    SET status = {ph}, first_seen_at = {ph}, attempts = 0, completed_at = '', error = '',
                        lookup_fingerprint = {ph}
                    WHERE issue_key = {ph} AND status <> {ph}""",
                (STATUS_PENDING, now.isoformat(), fingerprint, issue_key, STATUS_PENDING),
            )
            return bool(cur.rowcount)

    def _finish(self, issue_key: str, status: str, now: datetime, **cols: Any) -> bool:
        """Atomically move a pending row to a terminal status; False if another runner won."""
        ph = self._ph()
        sets = ["status", "completed_at", "last_attempt_at"]
        vals: list[Any] = [status, now.isoformat(), now.isoformat()]
        for name, value in cols.items():
            sets.append(name)
            vals.append(value if isinstance(value, str) else json.dumps(value))
        assignments = ", ".join(f"{name} = {ph}" for name in sets)
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE hr_entra_sync_issues SET {assignments} WHERE issue_key = {ph} AND status = {ph}",
                (*vals, issue_key, STATUS_PENDING),
            )
            return bool(cur.rowcount)

    # ------------------------------------------------------------------ JSM Forms

    def _cloud_id(self) -> str:
        if not getattr(self, "_cloud", ""):
            jira = self._jira_client()
            resp = jira.session.get(f"{jira.base_url}/_edge/tenant_info", timeout=30)
            resp.raise_for_status()
            self._cloud = str(resp.json().get("cloudId") or "")
            if not self._cloud:
                raise RuntimeError("Could not determine the Atlassian cloudId for the Forms API")
        return self._cloud

    def form_subject_email(self, issue_key: str, questions: tuple[str, ...]) -> str | None:
        """The employee's email from a JSM Form answer on the ticket (e.g. offboarding 'Employee Work Email')."""
        jira = self._jira_client()
        base = f"https://api.atlassian.com/jira/forms/cloud/{self._cloud_id()}/issue/{issue_key}/form"
        listing = jira.session.get(base, timeout=30)
        listing.raise_for_status()
        for form in listing.json() or []:
            detail = jira.session.get(f"{base}/{form['id']}", timeout=30)
            detail.raise_for_status()
            body = detail.json()
            labels = {qid: str(q.get("label") or "").strip().lower()
                      for qid, q in ((body.get("design") or {}).get("questions") or {}).items()}
            answers = (body.get("state") or {}).get("answers") or {}
            for qid, answer in answers.items():
                if labels.get(qid) in questions:
                    email = fmap.normalize_email(answer.get("text") if isinstance(answer, dict) else answer)
                    if email:
                        return email
        return None

    # ------------------------------------------------------------------ Entra

    def internal_domains(self) -> frozenset[str]:
        """Mail domains verified on our Entra tenant (cached 1h). Fails closed: raises if none can be loaded.

        Excludes the *.onmicrosoft.com routing domains and capability-less relay entries (CodeTwo, Egress).
        """
        if self._domains and time.monotonic() - self._domains_at < _DOMAINS_TTL_SECONDS:
            return self._domains
        domains: set[str] = set()
        try:
            org = self._azure_client().graph_request(
                "GET", "organization", params={"$select": "verifiedDomains"}
            )
            for tenant in org.get("value") or []:
                for d in tenant.get("verifiedDomains") or []:
                    name = str(d.get("name") or "").strip().lower()
                    if name and "Email" in str(d.get("capabilities") or "") and not name.endswith(".onmicrosoft.com"):
                        domains.add(name)
        except Exception:
            logger.exception("HR Entra sync: could not load the tenant's verified domains")
        if domains:
            self._domains, self._domains_at = frozenset(domains), time.monotonic()
        elif self._domains:
            logger.warning("HR Entra sync: verified-domain refresh returned nothing; using the previous list")
        else:
            raise RuntimeError("Entra verified domains unavailable; not looking up emails without the internal-domain rule")
        return self._domains

    def find_entra_users(self, email: str) -> list[dict[str, Any]]:
        safe = email.replace("'", "''")
        flt = f"mail eq '{safe}' or userPrincipalName eq '{safe}' or otherMails/any(c:c eq '{safe}')"
        resp = self._azure_client().graph_request(
            "GET",
            "users",
            params={
                "$filter": flt,
                "$select": ",".join(fmap.graph_select_properties()),
                "$count": "true",
                "$top": "5",
            },
            headers={"ConsistencyLevel": "eventual"},
        )
        return list(resp.get("value") or [])

    def _graph_users(self, flt: str) -> list[dict[str, Any]]:
        resp = self._azure_client().graph_request(
            "GET", "users",
            params={"$filter": flt, "$select": ",".join(fmap.graph_select_properties()), "$count": "true", "$top": "5"},
            headers={"ConsistencyLevel": "eventual"},
        )
        return [u for u in (resp.get("value") or []) if fmap.is_person_account(u)]

    def lookup_by_attributes(
        self, fields: dict[str, Any], tried: list[str]
    ) -> tuple[str, list[dict[str, Any]], str] | None:
        """Status Change: no email on the ticket, so identify the employee by Position ID, then exact first+last name.

        Returns (source, users, via) for the first attribute that matches anyone, else None. Only enabled,
        member, non-service accounts count, and the caller treats more than one user as ambiguous.
        """
        position = str(fields.get(fmap.POSITION_ID_FIELD_ID) or "").strip()
        if position:
            tried.append("Position ID")
            prop = fmap.EXT_PREFIX + "positionID"
            users = self._graph_users(f"{prop} eq '{position.replace(chr(39), chr(39) * 2)}'")
            if users:
                return "position", users, "position_id"
        first = str(fields.get(fmap.FIRST_NAME_FIELD_ID) or "").strip()
        last = str(fields.get(fmap.LAST_NAME_FIELD_ID) or "").strip()
        if first and last:
            tried.append("first and last name")
            q = lambda t: t.replace("'", "''")  # noqa: E731
            users = self._graph_users(f"givenName eq '{q(first)}' and surname eq '{q(last)}'")
            if users:
                return "name", users, "name"
        return None

    def fetch_manager(self, user_id: str) -> dict[str, Any] | None:
        try:
            return self._azure_client().graph_request(
                "GET", f"users/{user_id}/manager", params={"$select": "displayName,mail"}
            )
        except AzureApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    @staticmethod
    def _matched_via(user: dict[str, Any], email: str) -> str:
        if str(user.get("userPrincipalName") or "").lower() == email:
            return "upn"
        if str(user.get("mail") or "").lower() == email:
            return "mail"
        return "other_mail"

    # ------------------------------------------------------------------ core

    def _write_fields(self, issue_key: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        """PUT the fields; if Jira rejects specific ones (not on screen, bad option), drop them and retry once."""
        skipped: dict[str, str] = {}
        if not payload:
            return {}, skipped
        jira = self._jira_client()
        try:
            jira.update_issue_fields(issue_key, payload)
            return payload, skipped
        except requests.HTTPError as exc:
            resp = getattr(exc, "response", None)
            errors: dict[str, str] = {}
            if resp is not None and resp.status_code == 400:
                try:
                    errors = dict((resp.json() or {}).get("errors") or {})
                except ValueError:
                    errors = {}
            rejected = {k: str(v) for k, v in errors.items() if k in payload}
            if not rejected:
                raise
        skipped.update(rejected)
        remaining = {k: v for k, v in payload.items() if k not in rejected}
        if remaining:
            jira.update_issue_fields(issue_key, remaining)
        return remaining, skipped

    def sync_issue(
        self, issue_key: str, *, dry_run: bool = False, email_override: str | None = None
    ) -> dict[str, Any]:
        """Look the employee up in Entra and write mapped fields. Does not touch the store.

        ``email_override`` replaces the ticket's own email fields; it exists for testing a ticket
        that carries no email, and is rejected for anything but a dry run through the API.
        """
        issue = self._jira_client().get_issue(issue_key)
        fields = issue.get("fields") or {}
        # Candidates are (email, source, must_be_internal). The reporter and the Company email field must be on
        # a tenant domain; the Personal Email field exists for outside addresses, so it is exempt. A test-only
        # email override is exempt too.
        by_field: list[tuple[str, str]] = []
        reporter = None
        reporter_blocked = False
        if email_override:
            if fmap.normalize_email(email_override):
                by_field = [(fmap.normalize_email(email_override), "")]  # type: ignore[list-item]
        else:
            by_field = fmap.ticket_emails_by_field(fields)
            reporter = fmap.reporter_email(fields)
            reporter_blocked = bool(reporter) and not fmap.reporter_is_subject_candidate(fields)
            if reporter_blocked:
                reporter = None
        ticket_emails = [e for e, _ in by_field]
        candidates = [(e, "ticket", f == fmap.COMPANY_EMAIL_FIELD_ID) for e, f in by_field]
        if not email_override:
            form_questions = fmap.FORM_SUBJECT_EMAIL_QUESTIONS.get(
                str((fields.get("issuetype") or {}).get("name") or "").strip().lower()
            )
            form_email = self.form_subject_email(issue_key, form_questions) if form_questions else None
            if form_email and form_email not in ticket_emails:
                candidates.append((form_email, "form", True))
        if reporter and reporter not in ticket_emails:
            candidates.append((reporter, "reporter", True))
        form_email_found = any(src == "form" for _, src, _ in candidates)
        skipped_external: list[str] = []
        if any(restricted for _, _, restricted in candidates):
            domains = self.internal_domains()
            kept = []
            for email, source, restricted in candidates:
                if restricted and not fmap.is_internal_email(email, domains):
                    skipped_external.append(email)
                else:
                    kept.append((email, source, restricted))
            candidates = kept
        base = {
            "emails": [e for e, _, _ in candidates],
            "fingerprint": fmap.fingerprint(ticket_emails),
            "skipped_external": skipped_external,
            # No email on the ticket itself: only the reporter was a candidate (or was ruled out as external).
            "reporter_only": not ticket_emails and not form_email_found and (bool(candidates) or bool(skipped_external)),
            "reporter_blocked": reporter_blocked,
        }
        matched: tuple[dict[str, Any], str, str, str] | None = None  # (user, label, source, via)
        tried_attrs: list[str] = []
        for email, source, _ in candidates:
            users = self.find_entra_users(email)
            if source == "reporter":
                # The reporter is a guess at the subject, so only trust an enabled, person-style account.
                users = [u for u in users if fmap.is_person_account(u)]
            if len(users) > 1:
                return {"outcome": STATUS_AMBIGUOUS, "matched_email": email, "email_source": source,
                        "candidates": [u.get("userPrincipalName") for u in users], "attrs": tried_attrs, **base}
            if users:
                matched = (users[0], email, source, self._matched_via(users[0], email))
                break
        if matched is None and not email_override and fmap._issue_type(fields) in fmap.ATTRIBUTE_SUBJECT_TYPES:
            found = self.lookup_by_attributes(fields, tried_attrs)
            if found:
                source, users, via = found
                if len(users) > 1:
                    return {"outcome": STATUS_AMBIGUOUS, "matched_email": f"{source} on ticket", "email_source": source,
                            "candidates": [u.get("userPrincipalName") for u in users], "attrs": tried_attrs, **base}
                matched = (users[0], f"{source} on ticket", source, via)
        base["attrs"] = tried_attrs
        # Trimed roster sheet: fills any field Entra left empty, or supplies everything when Entra has no match.
        # Looked up by the same emails the Entra search considered (including ones skipped as external).
        sheet_row = None
        if not email_override:
            position = str(fields.get(fmap.POSITION_ID_FIELD_ID) or "") if fmap._issue_type(fields) in fmap.ATTRIBUTE_SUBJECT_TYPES else ""
            sheet_row = hr_trimed_sheet.find_row([e for e, _, _ in candidates] + skipped_external, position)
        if matched is None and sheet_row is None:
            if not candidates and not tried_attrs:
                return {"outcome": "no_email", **base}
            return {"outcome": "no_match", **base}

        if matched is not None:
            user, label, source, via = matched
            manager = self.fetch_manager(str(user["id"]))
            payload, empty = fmap.build_issue_fields(user, manager)
        else:
            user, label, source, via = {}, "trimed sheet", "sheet", "trimed_sheet"
            payload, empty = {}, []
        sheet_filled: list[str] = []
        if sheet_row is not None:
            sheet_payload, _ = hr_trimed_sheet.build_issue_fields(sheet_row)
            for field_id, value in sheet_payload.items():
                if field_id not in payload:
                    payload[field_id] = value
                    sheet_filled.append(field_id)
            names = {m.jira_field_id: m.jira_name for m in fmap.active_mappings()}
            empty = [n for n in empty if n not in {names.get(f) for f in sheet_filled}]
        kept: list[str] = []
        if fmap.is_fill_only(fields):
            payload, kept = fmap.drop_filled(payload, fields)
        if dry_run:
            written, skipped = payload, {}
        else:
            written, skipped = self._write_fields(issue_key, payload)
        return {
            "outcome": STATUS_SYNCED,
            "dry_run": dry_run,
            "matched_email": label,
            "email_source": source,
            "matched_upn": user.get("userPrincipalName") or "",
            "matched_via": via,
            "fields_written": written,
            "fields_skipped": skipped,
            "fields_kept": kept,
            "fields_from_sheet": sorted(sheet_filled),
            "entra_empty": empty,
            **base,
        }

    def _post_note(self, issue_key: str, text: str) -> None:
        self._jira_client().add_internal_comment(issue_key, text)

    def _process_pending(self, row: dict[str, Any], now: datetime) -> None:
        key = row["issue_key"]
        first_seen = _parse_dt(row["first_seen_at"]) or now
        window_over = now - first_seen >= timedelta(minutes=HR_ENTRA_SYNC_RETRY_MINUTES)
        try:
            result = self.sync_issue(key)
        except requests.HTTPError as exc:
            resp = getattr(exc, "response", None)
            if resp is not None and resp.status_code in (403, 404):
                self._finish(key, STATUS_FAILED, now, error=f"Jira {resp.status_code}: {exc}"[:1000])
                return
            self._retry_or_fail(key, now, window_over, exc)
            return
        except Exception as exc:  # noqa: BLE001 - Graph/Jira hiccups are retried inside the window
            self._retry_or_fail(key, now, window_over, exc)
            return

        outcome = result["outcome"]
        if outcome == "no_email" and result.get("reporter_blocked") and not result["emails"] and not result["skipped_external"]:
            # The reporter files this request type on someone else's behalf, so their profile is the wrong person's,
            # and nothing on the ticket identifies the employee yet. Do not guess and do not nag the ticket.
            self._finish(
                key, STATUS_NOT_FOUND, now,
                lookup_fingerprint=result["fingerprint"],
                error="Employee not identified: the reporter files this request type for someone else.",
            )
        elif outcome == "no_email" and result.get("reporter_only") and result["skipped_external"]:
            # Only an outside reporter (vendor/notification sender): nothing to look up, nothing to wait for.
            self._finish(
                key, STATUS_NOT_FOUND, now,
                lookup_fingerprint=result["fingerprint"], email_source="reporter",
                error=f"No email on ticket; reporter {result['skipped_external'][0]} is not on a tenant domain.",
            )
        elif outcome == STATUS_SYNCED:
            self._finish(
                key, STATUS_SYNCED, now,
                matched_upn=result["matched_upn"], matched_via=result["matched_via"],
                fields_written=sorted(result["fields_written"]), fields_skipped=result["fields_skipped"],
                lookup_fingerprint=result["fingerprint"], email_source=result["email_source"],
            )
            logger.info("HR Entra sync %s: wrote %d field(s) from %s", key, len(result["fields_written"]), result["matched_upn"])
        elif outcome == STATUS_AMBIGUOUS:
            self._finish_with_note(
                key, STATUS_AMBIGUOUS, now, result["fingerprint"],
                "Entra sync skipped: more than one Entra account matches "
                f"{result['matched_email']} ({', '.join(str(c) for c in result['candidates'])}). "
                "No fields were updated.",
            )
        elif window_over and result.get("reporter_only"):
            # Only the reporter was available and nothing matched (e.g. an external sender such as a vendor
            # notification): not worth a note on the ticket, but record the outcome.
            self._finish(
                key, STATUS_NOT_FOUND, now,
                lookup_fingerprint=result["fingerprint"], email_source="reporter",
                error=f"No email on ticket; reporter {result['emails'][0]} is not an Entra employee.",
            )
        elif window_over:
            external = result.get("skipped_external") or []
            if outcome == "no_email" and external:
                reason = f"{', '.join(external)} is not on a tenant domain, so it was not looked up"
            elif outcome == "no_email":
                reason = "no work or personal email address was found on this ticket"
            else:
                tried = result["emails"] + [f"the {a} on the ticket" for a in result.get("attrs") or []]
                reason = f"no Entra account matched {', '.join(tried)}"
            self._finish_with_note(
                key, STATUS_NOT_FOUND, now, result["fingerprint"],
                f"Entra sync: {reason} after {HR_ENTRA_SYNC_RETRY_MINUTES} minutes of retries. "
                "No fields were updated.",
            )
        else:
            self._record_attempt(key, now, fingerprint=result["fingerprint"])

    def _finish_with_note(self, key: str, status: str, now: datetime, fingerprint: str, note: str) -> None:
        if not self._finish(key, status, now, error=note[:1000], lookup_fingerprint=fingerprint):
            return  # another runner already finalized (and posted) this ticket
        try:
            self._post_note(key, note)
        except Exception:
            logger.exception("HR Entra sync: failed to post internal note on %s", key)

    def _retry_or_fail(self, key: str, now: datetime, window_over: bool, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("HR Entra sync %s attempt failed: %s", key, message)
        if window_over:
            self._finish(key, STATUS_FAILED, now, error=message[:1000])
        else:
            self._record_attempt(key, now, message)

    # ------------------------------------------------------------------ discovery + loop

    def discover_new_issues(self, now: datetime | None = None) -> int:
        now = now or _utcnow()
        projects = ", ".join(HR_ENTRA_SYNC_PROJECTS)
        jql = (
            f"project in ({projects}) AND created >= -{int(HR_ENTRA_SYNC_LOOKBACK_MINUTES)}m "
            "ORDER BY created ASC"
        )
        added = 0
        for issue in self._jira_client().search_all(jql, fields=["summary", "project"]):
            key = str(issue.get("key") or "")
            project = str(((issue.get("fields") or {}).get("project") or {}).get("key") or key.split("-")[0])
            if key and self._register(key, project, now):
                added += 1
        return added

    def _email_edited_since(self, issue_key: str, since: datetime) -> bool:
        """True if the ticket's work/personal email field was edited after ``since`` (from the changelog)."""
        jira = self._jira_client()
        base = f"{jira.base_url}/rest/api/3/issue/{issue_key}/changelog"
        head = jira.session.get(base, params={"maxResults": 1}, timeout=30)
        head.raise_for_status()
        total = int(head.json().get("total") or 0)
        resp = jira.session.get(base, params={"startAt": max(0, total - 100), "maxResults": 100}, timeout=30)
        resp.raise_for_status()
        for entry in resp.json().get("values") or []:
            created = _parse_dt(str(entry.get("created") or "").replace("+0000", "+00:00"))
            if created and created >= since and any(
                item.get("fieldId") in fmap.LOOKUP_EMAIL_FIELD_IDS for item in entry.get("items") or []
            ):
                return True
        return False

    def discover_email_changes(self, now: datetime | None = None) -> int:
        """Re-queue tickets whose work/personal email changed, so the new address is looked up in Entra."""
        now = now or _utcnow()
        projects = ", ".join(HR_ENTRA_SYNC_PROJECTS)
        jql = f"project in ({projects}) AND updated >= -{int(HR_ENTRA_SYNC_LOOKBACK_MINUTES)}m ORDER BY updated ASC"
        since = now - timedelta(minutes=HR_ENTRA_SYNC_LOOKBACK_MINUTES)
        reopened = 0
        for issue in self._jira_client().search_all(jql, fields=[*fmap.LOOKUP_EMAIL_FIELD_IDS, "project"]):
            key = str(issue.get("key") or "")
            fields = issue.get("fields") or {}
            fp = fmap.fingerprint(fmap.ticket_emails(fields))
            if not key or not fp:
                continue
            row = self.get_row(key)
            if row is None:
                # Never seen (older than the creation lookback): only act if the email field was really edited.
                project = str((fields.get("project") or {}).get("key") or key.split("-")[0])
                if self._email_edited_since(key, since) and self._register(key, project, now):
                    reopened += 1
            elif row["status"] != STATUS_PENDING and row["lookup_fingerprint"] != fp:
                if self._reopen(key, fp, now):
                    reopened += 1
        return reopened

    def run_cycle_sync(self, now: datetime | None = None) -> dict[str, int]:
        now = now or _utcnow()
        added = self.discover_new_issues(now)
        added += self.discover_email_changes(now)
        pending = self.list_rows(status=STATUS_PENDING, limit=200)
        for row in reversed(pending):  # oldest first
            self._process_pending(row, _utcnow())
        return {"discovered": added, "processed": len(pending)}

    async def run_cycle(self) -> dict[str, int]:
        return await asyncio.to_thread(self.run_cycle_sync)

    def start_background_runner(self) -> None:
        self._bg_task = asyncio.get_event_loop().create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        while True:
            try:
                if HR_ENTRA_SYNC_ENABLED:
                    await self.run_cycle()
                await asyncio.sleep(max(15, HR_ENTRA_SYNC_POLL_SECONDS))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("HR Entra sync loop error")
                await asyncio.sleep(120)


hr_entra_sync_job = HrEntraSyncJob()
