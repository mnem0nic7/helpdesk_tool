"""Office 365 requestor mirroring and Jira customer reconciliation."""

from __future__ import annotations

import logging
import re
from typing import Any

from ai_client import _extract_reporter_hint_from_text, extract_adf_text
from config import JIRA_PROJECT
from jira_client import JiraClient
from metrics import _is_open
from requestor_sync_store import requestor_sync_store
from sla_engine import SLAConfig

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
_REPORTER_EMAIL_RE = re.compile(r"Reporter Email:\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?", re.I)
_REPORTER_NAME_RE = re.compile(r"Reporter Name:\s*([^\n|]+)", re.I)
_FULL_NAME_RE = re.compile(r"Full name of user:\s*([^\n|]+)", re.I)
_EMAIL_ADDRESS_RE = re.compile(r"Email address:\s*<?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})>?", re.I)
_FROM_RE = re.compile(r"From:\s*([^<\n|]+?)\s*<\s*([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})\s*>", re.I)
_GENERIC_ANGLE_RE = re.compile(r"<\s*([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})\s*>", re.I)


def _normalize_email(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text.startswith("mailto:"):
        text = text[7:]
    text = text.strip(" <>[](){}\"'.,;:")
    match = _EMAIL_RE.search(text)
    if not match:
        return ""
    return match.group(0).lower()


def _compact_name(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text.strip(" \t|:-")


class RequestorSyncService:
    """Reconcile ticket requestors against Entra and Jira customers."""

    def __init__(self, store=requestor_sync_store, client: JiraClient | None = None) -> None:
        self._store = store
        self._client = client
        self._sla_config = SLAConfig()
        self._service_desk_ids: dict[str, str] = {}

    def _jira_client(self) -> JiraClient:
        return self._client or JiraClient()

    def refresh_directory_emails(self, users: list[dict[str, Any]]) -> int:
        entries: list[dict[str, str]] = []
        for user in users:
            extra = user.get("extra") if isinstance(user.get("extra"), dict) else {}
            canonical_email = _normalize_email(user.get("primary_mail") or user.get("mail") or user.get("principal_name"))
            account_class = str(user.get("account_class") or extra.get("account_class") or "").strip()
            display_name = str(user.get("display_name") or "").strip()
            user_id = str(user.get("id") or "").strip()
            candidates: list[tuple[str, str]] = []

            mail = _normalize_email(user.get("mail"))
            if mail:
                candidates.append((mail, "mail"))

            principal_name = _normalize_email(user.get("principal_name"))
            if principal_name:
                candidates.append((principal_name, "upn"))

            aliases = user.get("email_aliases")
            if not isinstance(aliases, list):
                aliases = []
                for raw in str(extra.get("proxy_addresses") or "").split(","):
                    normalized = _normalize_email(raw)
                    if normalized:
                        aliases.append(normalized)
            for alias in aliases:
                normalized_alias = _normalize_email(alias)
                if normalized_alias:
                    candidates.append((normalized_alias, "proxy"))

            if canonical_email:
                entries.append(
                    {
                        "email_key": canonical_email,
                        "entra_user_id": user_id,
                        "display_name": display_name,
                        "canonical_email": canonical_email,
                        "account_class": account_class,
                        "source_kind": "canonical",
                    }
                )

            seen: set[tuple[str, str]] = set()
            for email_key, source_kind in candidates:
                key = (email_key, source_kind)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    {
                        "email_key": email_key,
                        "entra_user_id": user_id,
                        "display_name": display_name,
                        "canonical_email": canonical_email or email_key,
                        "account_class": account_class,
                        "source_kind": source_kind,
                    }
                )

        self._store.replace_directory_emails(entries)
        return len(entries)

    def integration_reporter_names(self) -> set[str]:
        settings = self._sla_config.get_settings()
        return {
            item.strip().lower()
            for item in str(settings.get("integration_reporters") or "").split(",")
            if item.strip()
        }

    def _reporter_is_integration(self, reporter_obj: dict[str, Any]) -> bool:
        display_name = str(reporter_obj.get("displayName") or "").strip().lower()
        email_address = _normalize_email(reporter_obj.get("emailAddress"))
        if display_name and display_name in self.integration_reporter_names():
            return True
        if email_address and any(name in email_address for name in ("jiraocc", "osijiraocc", "integration", "phisher")):
            return True
        return False

    def extract_requestor_identity(self, issue: dict[str, Any]) -> dict[str, str]:
        fields = issue.get("fields", {})
        reporter_obj = fields.get("reporter") if isinstance(fields.get("reporter"), dict) else {}
        reporter_email = _normalize_email(reporter_obj.get("emailAddress"))
        if reporter_email and not self._reporter_is_integration(reporter_obj):
            return {
                "email": reporter_email,
                "source": "reporter",
                "display_name": _compact_name(reporter_obj.get("displayName")),
                "reporter_hint": "",
            }

        description = extract_adf_text(fields.get("description"))
        if not description:
            return {"email": "", "source": "", "display_name": "", "reporter_hint": ""}

        match = _REPORTER_EMAIL_RE.search(description)
        if match:
            return {
                "email": _normalize_email(match.group(1)),
                "source": "reporter_email",
                "display_name": _compact_name((_REPORTER_NAME_RE.search(description) or ["", ""])[1]),
                "reporter_hint": _extract_reporter_hint_from_text(description),
            }

        match = _EMAIL_ADDRESS_RE.search(description)
        if match:
            return {
                "email": _normalize_email(match.group(1)),
                "source": "email_address",
                "display_name": _compact_name((_FULL_NAME_RE.search(description) or ["", ""])[1]),
                "reporter_hint": _extract_reporter_hint_from_text(description),
            }

        match = _FROM_RE.search(description)
        if match:
            return {
                "email": _normalize_email(match.group(2)),
                "source": "from_header",
                "display_name": _compact_name(match.group(1)),
                "reporter_hint": _extract_reporter_hint_from_text(description),
            }

        match = _GENERIC_ANGLE_RE.search(description)
        if match:
            return {
                "email": _normalize_email(match.group(1)),
                "source": "generic_email",
                "display_name": "",
                "reporter_hint": _extract_reporter_hint_from_text(description),
            }

        return {
            "email": "",
            "source": "",
            "display_name": "",
            "reporter_hint": _extract_reporter_hint_from_text(description),
        }

    def _get_service_desk_id(self, issue: dict[str, Any]) -> str:
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        project_obj = fields.get("project") if isinstance(fields.get("project"), dict) else {}
        project_key = str(project_obj.get("key") or JIRA_PROJECT or "OIT").strip().upper()
        if project_key in self._service_desk_ids:
            return self._service_desk_ids[project_key]
        resolved = self._jira_client().get_service_desk_id_for_project(project_key)
        if not resolved:
            raise RuntimeError(f"Could not resolve Jira Service Management service desk for {project_key}")
        self._service_desk_ids[project_key] = resolved
        return resolved

    @staticmethod
    def _exact_email_matches(rows: list[dict[str, Any]], email: str) -> list[dict[str, Any]]:
        normalized_email = _normalize_email(email)
        matches: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_email = _normalize_email(row.get("emailAddress"))
            if row_email != normalized_email:
                continue
            account_id = str(row.get("accountId") or "").strip()
            if account_id:
                matches[account_id] = row
        return list(matches.values())

    def _resolve_existing_jira_identity(self, email: str, service_desk_id: str) -> tuple[dict[str, Any] | None, str]:
        email_key = _normalize_email(email)
        cached = self._store.get_recent_success_for_email(email_key)
        if cached and str(cached.get("jira_account_id") or "").strip():
            return {
                "accountId": str(cached.get("jira_account_id") or "").strip(),
                "displayName": str(cached.get("jira_display_name") or "").strip(),
                "emailAddress": str(cached.get("canonical_email") or email_key),
            }, ""

        client = self._jira_client()
        users = self._exact_email_matches(client.search_users(email_key, max_results=50), email_key)
        customers = self._exact_email_matches(client.get_service_desk_customers(service_desk_id, query=email_key), email_key)

        matches: dict[str, dict[str, Any]] = {}
        for row in [*users, *customers]:
            account_id = str(row.get("accountId") or "").strip()
            if account_id:
                matches[account_id] = row

        if not matches:
            return None, ""
        if len(matches) > 1:
            return None, "Multiple Jira users/customers match this email"
        return next(iter(matches.values())), ""

    @staticmethod
    def _patch_issue_reporter(issue: dict[str, Any], *, account_id: str, display_name: str, email: str) -> None:
        fields = issue.setdefault("fields", {})
        fields["reporter"] = {
            "accountId": account_id,
            "displayName": display_name,
            "emailAddress": email,
        }

    def _build_identity_payload(
        self,
        issue: dict[str, Any],
        *,
        extracted_email: str,
        directory_matches: list[dict[str, Any]] | None = None,
        state: dict[str, Any] | None = None,
        fallback_status: str = "",
        fallback_message: str = "",
    ) -> dict[str, Any]:
        row = state or self._store.get_ticket_state(issue.get("key", ""))
        email_key = _normalize_email(extracted_email)
        matches = directory_matches if directory_matches is not None else (self._store.get_directory_matches(email_key) if email_key else [])
        return {
            "extracted_email": str((row or {}).get("extracted_email") or extracted_email or "").strip().lower(),
            "directory_match": bool((row or {}).get("canonical_email") or matches),
            "jira_account_id": str((row or {}).get("jira_account_id") or "").strip(),
            "jira_status": str((row or {}).get("sync_status") or fallback_status or ("no_email_extracted" if not extracted_email else "")),
            "message": str((row or {}).get("message") or fallback_message or "").strip(),
        }

    def get_requestor_identity(self, issue: dict[str, Any]) -> dict[str, Any]:
        extracted = self.extract_requestor_identity(issue)
        if extracted["email"]:
            matches = self._store.get_directory_matches(_normalize_email(extracted["email"]))
            return self._build_identity_payload(
                issue,
                extracted_email=extracted["email"],
                directory_matches=matches,
                fallback_status="match_pending" if matches else "not_in_office365",
                fallback_message=(
                    "Exact Office 365 directory match found."
                    if matches
                    else "No exact Office 365 directory match found for the extracted requestor email."
                ),
            )
        return self._build_identity_payload(
            issue,
            extracted_email="",
            fallback_status="no_email_extracted",
            fallback_message="No requestor email was extracted from this ticket yet.",
        )

    def has_recent_ticket_state(self, ticket_key: str, *, max_age_minutes: int = 60) -> bool:
        return self._store.has_recent_ticket_state(ticket_key, max_age_minutes=max_age_minutes)

    def needs_reconcile(self, issue: dict[str, Any], *, open_only: bool = False, max_age_minutes: int = 60) -> bool:
        key = str(issue.get("key") or "").strip()
        if not key:
            return False
        if open_only and not _is_open(issue):
            return False
        if self.has_recent_ticket_state(key, max_age_minutes=max_age_minutes):
            return False
        extracted = self.extract_requestor_identity(issue)
        return bool(extracted["email"])

    def reconcile_issue(self, issue: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        key = str(issue.get("key") or "").strip().upper()
        if not key:
            return {
                "updated": False,
                "message": "Ticket key missing.",
                "requestor_identity": {
                    "extracted_email": "",
                    "directory_match": False,
                    "jira_account_id": "",
                    "jira_status": "missing_ticket_key",
                    "message": "Ticket key missing.",
                },
            }

        extracted = self.extract_requestor_identity(issue)
        extracted_email = _normalize_email(extracted["email"])
        if not extracted_email:
            message = "No requestor email was extracted from this ticket."
            return {
                "updated": False,
                "message": message,
                "requestor_identity": self._build_identity_payload(
                    issue,
                    extracted_email="",
                    fallback_status="no_email_extracted",
                    fallback_message=message,
                ),
            }

        email_key = extracted_email
        directory_matches = self._store.get_directory_matches(email_key)
        if not directory_matches:
            message = "No exact Office 365 directory match was found for this requestor email."
            self._store.upsert_requestor_link(
                email_key=email_key,
                ticket_key=key,
                extracted_email=extracted_email,
                sync_status="not_in_office365",
                message=message,
            )
            state = self._store.get_ticket_state(key)
            return {
                "updated": False,
                "message": message,
                "requestor_identity": self._build_identity_payload(
                    issue,
                    extracted_email=extracted_email,
                    directory_matches=[],
                    state=state,
                ),
            }

        unique_user_ids = {str(item.get("entra_user_id") or "").strip() for item in directory_matches}
        unique_canonical_emails = {str(item.get("canonical_email") or "").strip().lower() for item in directory_matches}
        if len(unique_user_ids) > 1 or len(unique_canonical_emails) > 1:
            message = "Multiple Office 365 identities matched this requestor email."
            self._store.upsert_requestor_link(
                email_key=email_key,
                ticket_key=key,
                extracted_email=extracted_email,
                sync_status="ambiguous_directory_match",
                message=message,
            )
            state = self._store.get_ticket_state(key)
            return {
                "updated": False,
                "message": message,
                "requestor_identity": self._build_identity_payload(
                    issue,
                    extracted_email=extracted_email,
                    directory_matches=directory_matches,
                    state=state,
                ),
            }

        directory_match = directory_matches[0]
        canonical_email = str(directory_match.get("canonical_email") or email_key).strip().lower()
        directory_display_name = str(directory_match.get("display_name") or "").strip()
        reporter_obj = (issue.get("fields") or {}).get("reporter") or {}
        current_account_id = str(reporter_obj.get("accountId") or "").strip()

        service_desk_id = self._get_service_desk_id(issue)
        jira_identity, conflict_error = self._resolve_existing_jira_identity(canonical_email, service_desk_id)
        if conflict_error:
            self._store.upsert_requestor_link(
                email_key=email_key,
                ticket_key=key,
                extracted_email=extracted_email,
                directory_user_id=str(directory_match.get("entra_user_id") or "").strip(),
                directory_display_name=directory_display_name,
                canonical_email=canonical_email,
                sync_status="jira_conflict",
                message=conflict_error,
            )
            state = self._store.get_ticket_state(key)
            return {
                "updated": False,
                "message": conflict_error,
                "requestor_identity": self._build_identity_payload(
                    issue,
                    extracted_email=extracted_email,
                    directory_matches=directory_matches,
                    state=state,
                ),
            }

        created_customer = False
        if jira_identity is None:
            jira_identity = self._jira_client().create_customer(
                email=canonical_email,
                display_name=directory_display_name or extracted.get("display_name") or canonical_email,
            )
            created_customer = True

        jira_account_id = str(jira_identity.get("accountId") or "").strip()
        jira_display_name = str(jira_identity.get("displayName") or directory_display_name or canonical_email).strip()
        if not jira_account_id:
            message = "Jira did not return an account ID for this requestor."
            self._store.upsert_requestor_link(
                email_key=email_key,
                ticket_key=key,
                extracted_email=extracted_email,
                directory_user_id=str(directory_match.get("entra_user_id") or "").strip(),
                directory_display_name=directory_display_name,
                canonical_email=canonical_email,
                sync_status="sync_failed",
                message=message,
            )
            state = self._store.get_ticket_state(key)
            return {
                "updated": False,
                "message": message,
                "requestor_identity": self._build_identity_payload(
                    issue,
                    extracted_email=extracted_email,
                    directory_matches=directory_matches,
                    state=state,
                ),
            }

        client = self._jira_client()
        client.add_customers_to_service_desk(service_desk_id, [jira_account_id])

        updated = False
        if force or current_account_id != jira_account_id:
            client.update_reporter(key, jira_account_id)
            updated = True

        self._patch_issue_reporter(
            issue,
            account_id=jira_account_id,
            display_name=jira_display_name,
            email=canonical_email,
        )

        status = "created_jira_customer" if created_customer else ("updated_reporter" if updated else "already_synced")
        message = (
            f"Created Jira customer and synced reporter to {jira_display_name}."
            if created_customer
            else (
                f"Reporter synced to {jira_display_name}."
                if updated
                else f"Reporter already matched {jira_display_name}."
            )
        )
        self._store.upsert_requestor_link(
            email_key=email_key,
            ticket_key=key,
            extracted_email=extracted_email,
            directory_user_id=str(directory_match.get("entra_user_id") or "").strip(),
            directory_display_name=directory_display_name,
            canonical_email=canonical_email,
            jira_account_id=jira_account_id,
            jira_display_name=jira_display_name,
            sync_status=status,
            message=message,
        )
        state = self._store.get_ticket_state(key)
        return {
            "updated": updated or created_customer,
            "message": message,
            "requestor_identity": self._build_identity_payload(
                issue,
                extracted_email=extracted_email,
                directory_matches=directory_matches,
                state=state,
            ),
        }

    def maybe_reconcile_issue(self, issue: dict[str, Any]) -> dict[str, Any]:
        if self.needs_reconcile(issue):
            try:
                return self.reconcile_issue(issue)
            except Exception:
                logger.exception("Requestor sync failed for %s", issue.get("key"))
        return {
            "updated": False,
            "message": "",
            "requestor_identity": self.get_requestor_identity(issue),
        }

    def reconcile_issues(self, issues: list[dict[str, Any]], *, open_only: bool = False) -> None:
        for issue in issues:
            if not self.needs_reconcile(issue, open_only=open_only):
                continue
            try:
                self.reconcile_issue(issue)
            except Exception:
                logger.exception("Requestor sync failed for %s", issue.get("key"))

    def list_recent_status(self, *, limit: int = 100, failures_only: bool = False) -> list[dict[str, Any]]:
        return self._store.list_recent_status(limit=limit, failures_only=failures_only)


requestor_sync_service = RequestorSyncService()
