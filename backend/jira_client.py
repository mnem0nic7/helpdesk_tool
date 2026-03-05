"""Jira REST API v3 client for the OIT Helpdesk Dashboard."""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from config import JIRA_EMAIL, JIRA_API_TOKEN, JIRA_BASE_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default fields to request on search queries
# ---------------------------------------------------------------------------
FIELDS: list[str] = [
    "summary",
    "description",
    "issuetype",
    "status",
    "statusCategory",
    "priority",
    "resolution",
    "resolutiondate",
    "created",
    "updated",
    "creator",
    "reporter",
    "assignee",
    "comment",
    # Custom fields
    "customfield_11102",
    "customfield_11239",
    "customfield_11117",
    "customfield_11301",
    "customfield_11249",
    "customfield_11264",
    "customfield_11266",
    "customfield_11267",
    "customfield_11268",
    "customfield_10001",
    "customfield_10010",  # Request type
    # Metadata
    "labels",
    "components",
    "statuscategorychangedate",
]


class JiraClient:
    """Thin wrapper around the Jira Cloud REST API v3."""

    def __init__(
        self,
        base_url: str = JIRA_BASE_URL,
        email: str = JIRA_EMAIL,
        token: str = JIRA_API_TOKEN,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(email, token)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_excluded(issue: dict[str, Any]) -> bool:
        """Return True if the issue should be excluded from metrics.

        Excludes issues whose labels or summary contain "oasisdev"
        (case-insensitive).
        """
        fields = issue.get("fields", {})

        # Check labels
        labels = fields.get("labels") or []
        for label in labels:
            if "oasisdev" in label.lower():
                return True

        # Check summary
        summary = fields.get("summary") or ""
        if "oasisdev" in summary.lower():
            return True

        return False

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        jql: str,
        max_results: int = 100,
        start_at: int = 0,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a JQL search via POST /rest/api/3/search/jql.

        Returns the raw JSON response dict.
        """
        url = f"{self.base_url}/rest/api/3/search/jql"
        payload: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields or FIELDS,
        }
        # The v3 search/jql endpoint uses nextPageToken, not startAt,
        # but we accept start_at for simple one-page fetches.
        if start_at:
            payload["startAt"] = start_at

        resp = self.session.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def search_all(
        self,
        jql: str,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through ALL results for a JQL query using nextPageToken.

        Returns a flat list of issue dicts.
        """
        url = f"{self.base_url}/rest/api/3/search/jql"
        all_issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        request_fields = fields or FIELDS

        while True:
            payload: dict[str, Any] = {
                "jql": jql,
                "maxResults": 100,
                "fields": request_fields,
            }
            if next_page_token:
                payload["nextPageToken"] = next_page_token

            resp = self.session.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            issues = data.get("issues", [])
            all_issues.extend(issues)

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

            logger.debug(
                "Fetched %d issues so far (nextPageToken: %s)",
                len(all_issues),
                next_page_token[:20] if next_page_token else "None",
            )

        logger.info("search_all complete: %d issues for JQL: %s", len(all_issues), jql)
        return all_issues

    # ------------------------------------------------------------------
    # Single-issue operations
    # ------------------------------------------------------------------

    def get_issue(self, key: str) -> dict[str, Any]:
        """GET /rest/api/3/issue/{key}"""
        url = f"{self.base_url}/rest/api/3/issue/{key}"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json()

    def get_transitions(self, key: str) -> list[dict[str, Any]]:
        """GET /rest/api/3/issue/{key}/transitions"""
        url = f"{self.base_url}/rest/api/3/issue/{key}/transitions"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json().get("transitions", [])

    def transition_issue(self, key: str, transition_id: str) -> None:
        """POST /rest/api/3/issue/{key}/transitions"""
        url = f"{self.base_url}/rest/api/3/issue/{key}/transitions"
        payload = {"transition": {"id": transition_id}}
        resp = self.session.post(url, json=payload)
        resp.raise_for_status()

    def assign_issue(self, key: str, account_id: str) -> None:
        """PUT /rest/api/3/issue/{key}/assignee"""
        url = f"{self.base_url}/rest/api/3/issue/{key}/assignee"
        payload = {"accountId": account_id}
        resp = self.session.put(url, json=payload)
        resp.raise_for_status()

    def update_priority(self, key: str, priority_name: str) -> None:
        """PUT /rest/api/3/issue/{key} to change priority."""
        url = f"{self.base_url}/rest/api/3/issue/{key}"
        payload = {"fields": {"priority": {"name": priority_name}}}
        resp = self.session.put(url, json=payload)
        resp.raise_for_status()

    def add_comment(self, key: str, body_text: str) -> dict[str, Any]:
        """POST /rest/api/3/issue/{key}/comment using ADF format."""
        url = f"{self.base_url}/rest/api/3/issue/{key}/comment"
        payload = {
            "body": {
                "version": 1,
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": body_text,
                            }
                        ],
                    }
                ],
            }
        }
        resp = self.session.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Request types (JSM)
    # ------------------------------------------------------------------

    def get_request_types(self, service_desk_id: str) -> list[dict[str, Any]]:
        """GET /rest/servicedeskapi/servicedesk/{id}/requesttype"""
        url = f"{self.base_url}/rest/servicedeskapi/servicedesk/{service_desk_id}/requesttype"
        all_types: list[dict[str, Any]] = []
        start = 0
        while True:
            resp = self.session.get(url, params={"start": start, "limit": 100})
            resp.raise_for_status()
            data = resp.json()
            all_types.extend(data.get("values", []))
            if data.get("isLastPage", True):
                break
            start += len(data.get("values", []))
        return all_types

    def set_request_type(self, key: str, request_type_id: str) -> None:
        """Change request type via JSM: POST /rest/servicedeskapi/request/{key}/requesttype"""
        url = f"{self.base_url}/rest/servicedeskapi/request/{key}/requesttype"
        payload = {"requestTypeId": request_type_id}
        resp = self.session.post(url, json=payload)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_users_assignable(self, project: str) -> list[dict[str, Any]]:
        """GET /rest/api/3/user/assignable/search?project={project}"""
        url = f"{self.base_url}/rest/api/3/user/assignable/search"
        params = {"project": project}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_priorities(self) -> list[dict[str, Any]]:
        """GET /rest/api/3/priority — returns all configured priorities."""
        url = f"{self.base_url}/rest/api/3/priority"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json()
