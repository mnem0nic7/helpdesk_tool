"""Best-effort local sync of authoritative daily follow-up data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import JIRA_FOLLOWUP_AGENT_GROUPS
from followup_authority import (
    LOCAL_FOLLOWUP_SOURCE_FIELD,
    LOCAL_FOLLOWUP_SOURCE_VALUE,
    LOCAL_FOLLOWUP_STATUS_FIELD,
    LOCAL_FOLLOWUP_SYNCED_UPDATED_FIELD,
    apply_local_followup_fields,
    compute_followup_from_public_agent_comments,
    parse_dt,
)
from jira_client import JiraClient

logger = logging.getLogger(__name__)


class FollowUpSyncService:
    """Populate authoritative public-comment follow-up values locally."""

    def __init__(self, client: JiraClient | None = None) -> None:
        self._client = client
        self._agent_account_ids: set[str] | None = None

    def _jira_client(self) -> JiraClient:
        return self._client or JiraClient()

    def _load_agent_account_ids(self) -> set[str]:
        if self._agent_account_ids is not None:
            return self._agent_account_ids
        account_ids: set[str] = set()
        client = self._jira_client()
        for group_name in JIRA_FOLLOWUP_AGENT_GROUPS:
            for member in client.get_group_members(group_name):
                account_id = str(member.get("accountId") or "").strip()
                if account_id:
                    account_ids.add(account_id)
        self._agent_account_ids = account_ids
        return account_ids

    @staticmethod
    def _is_recent_or_open(issue: dict[str, Any], *, recent_days: int) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(recent_days, 1))
        fields = issue.get("fields") or {}
        status_category = str((((fields.get("status") or {}).get("statusCategory") or {}).get("name") or "")).strip().lower()
        if status_category != "done":
            return True
        for raw in (fields.get("created"), fields.get("updated"), fields.get("resolutiondate")):
            parsed = parse_dt(raw)
            if parsed and parsed >= cutoff:
                return True
        return False

    @staticmethod
    def _already_synced_for_current_issue(issue: dict[str, Any]) -> bool:
        fields = issue.get("fields") or {}
        synced_for_updated = str(fields.get(LOCAL_FOLLOWUP_SYNCED_UPDATED_FIELD) or "").strip()
        current_updated = str(fields.get("updated") or "").strip()
        status = str(fields.get(LOCAL_FOLLOWUP_STATUS_FIELD) or "").strip()
        source = str(fields.get(LOCAL_FOLLOWUP_SOURCE_FIELD) or "").strip()
        return bool(
            status in {"Running", "Met", "BREACHED"}
            and synced_for_updated
            and synced_for_updated == current_updated
            and source == LOCAL_FOLLOWUP_SOURCE_VALUE
        )

    @staticmethod
    def _cached_comment_payload(issue: dict[str, Any]) -> list[dict[str, Any]] | None:
        fields = issue.get("fields") or {}
        if "comment" not in fields:
            return None
        comment_obj = fields.get("comment") or {}
        comments = comment_obj.get("comments") or []
        total = int(comment_obj.get("total") or len(comments))
        if total > len(comments):
            return None
        normalized: list[dict[str, Any]] = []
        for comment in comments:
            if not isinstance(comment, dict):
                return None
            if "public" in comment:
                is_public = bool(comment.get("public"))
            elif "jsdPublic" in comment:
                is_public = bool(comment.get("jsdPublic"))
            else:
                return None
            normalized_comment = dict(comment)
            normalized_comment["public"] = is_public
            normalized.append(normalized_comment)
        return normalized

    def reconcile_issue(self, issue: dict[str, Any], *, force: bool = False) -> bool:
        key = str(issue.get("key") or "").strip()
        if not key:
            return False
        if not force and self._already_synced_for_current_issue(issue):
            return False
        comments = self._cached_comment_payload(issue)
        if comments is None:
            comments = self._jira_client().get_request_comments(key)
        computed = compute_followup_from_public_agent_comments(
            issue,
            comments,
            agent_account_ids=self._load_agent_account_ids(),
        )
        apply_local_followup_fields(issue, computed)
        return True

    def reconcile_issues(
        self,
        issues: list[dict[str, Any]],
        *,
        force: bool = False,
        recent_days: int = 35,
    ) -> int:
        changed = 0
        for issue in issues:
            if not force and not self._is_recent_or_open(issue, recent_days=recent_days):
                continue
            try:
                if self.reconcile_issue(issue, force=force):
                    changed += 1
            except Exception:
                logger.exception("Follow-up authority sync failed for %s", issue.get("key"))
        return changed


followup_sync_service = FollowUpSyncService()
