"""Helpers for Jira writes with Atlassian OAuth and shared-account fallback."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from auth import get_valid_atlassian_connection
from jira_client import JiraClient

logger = logging.getLogger(__name__)

FALLBACK_AUDIT_MARKER = "[MoveDocs fallback audit]"


@dataclass
class JiraWriteContext:
    """Resolved identity and client for one Jira mutation."""

    client: JiraClient
    mode: str
    actor_email: str
    actor_name: str
    connected: bool

    @property
    def is_fallback(self) -> bool:
        return self.mode != "jira_user"


def get_jira_write_context(
    session: dict[str, Any] | None,
    *,
    shared_client: JiraClient | None = None,
) -> JiraWriteContext:
    shared = shared_client or JiraClient()
    actor_email = str((session or {}).get("email") or "").strip()
    actor_name = str((session or {}).get("name") or actor_email or "Unknown User").strip()
    if actor_email:
        connection = get_valid_atlassian_connection(actor_email)
        if connection:
            return JiraWriteContext(
                client=JiraClient.for_atlassian_oauth(
                    cloud_id=str(connection.get("cloud_id") or ""),
                    access_token=str(connection.get("access_token") or ""),
                ),
                mode="jira_user",
                actor_email=actor_email,
                actor_name=str(connection.get("atlassian_account_name") or actor_name),
                connected=True,
            )
    return JiraWriteContext(
        client=shared,
        mode="fallback_it_app",
        actor_email=actor_email,
        actor_name=actor_name,
        connected=False,
    )


def fallback_actor_line(session: dict[str, Any] | None) -> str:
    actor_email = str((session or {}).get("email") or "").strip() or "unknown@example.com"
    actor_name = str((session or {}).get("name") or actor_email).strip()
    return f"[MoveDocs fallback actor: {actor_name} <{actor_email}>]"


def prepend_fallback_actor_line(text: str, session: dict[str, Any] | None) -> str:
    prefix = fallback_actor_line(session)
    body = str(text or "").strip()
    return f"{prefix}\n\n{body}" if body else prefix


def append_fallback_actor_block(text: str, session: dict[str, Any] | None) -> str:
    body = str(text or "").strip()
    suffix = fallback_actor_line(session)
    return f"{body}\n\n{suffix}" if body else suffix


def add_fallback_internal_audit_note(
    key: str,
    *,
    action_summary: str,
    session: dict[str, Any] | None,
    shared_client: JiraClient | None = None,
) -> None:
    client = shared_client or JiraClient()
    note = (
        f"{FALLBACK_AUDIT_MARKER}\n"
        f"{fallback_actor_line(session)}\n\n"
        f"MoveDocs performed this Jira update through the shared it-app identity.\n"
        f"Action: {action_summary}"
    )
    try:
        client.add_request_comment(key, note, public=False)
    except Exception:
        logger.exception("Failed to add fallback audit note for %s", key)
