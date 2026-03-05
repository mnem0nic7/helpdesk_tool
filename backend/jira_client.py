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
    # Core fields
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
    # SLA timers (JSM)
    "customfield_11264",   # Time to resolution
    "customfield_11266",   # Time to first response
    "customfield_11267",   # Time to close after resolution
    "customfield_11268",   # Time to review normal change
    # Custom fields with data
    "customfield_11102",   # Request Type (JSM widget — also enriched via JSM API)
    "customfield_11239",   # Work category
    "customfield_11117",   # SLT Projects
    "customfield_10010",   # Epic Color (null — RT comes from JSM enrichment)
    "customfield_11121",   # Steps To Re-Create The Issue (ADF, useful for AI triage)
    "customfield_10200",   # Business Priority
    "customfield_10700",   # Organizations (customer org)
    "customfield_11217",   # Request language
    # Metadata
    "labels",
    "components",
    "attachment",
    "issuelinks",
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
    # Request type enrichment
    # ------------------------------------------------------------------

    def enrich_request_types(
        self,
        issues: list[dict[str, Any]],
        existing_cache: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Fetch request types via JSM per-ticket API and inject into issue fields.

        The standard Jira REST API returns null for customfield_10010,
        so we fetch each ticket's request type individually via
        GET /rest/servicedeskapi/request/{key}?expand=requestType.

        If *existing_cache* is provided, carries forward already-known request
        types so we only call the JSM API for truly missing tickets.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # First, carry forward known request types from existing cache
        if existing_cache:
            carried = 0
            for issue in issues:
                key = issue.get("key", "")
                cached = existing_cache.get(key, {})
                cached_rt = (cached.get("fields", {}).get("customfield_10010") or {}).get("requestType")
                if cached_rt:
                    issue.setdefault("fields", {})["customfield_10010"] = {"requestType": cached_rt}
                    carried += 1
            if carried:
                logger.info("Carried forward %d request types from cache", carried)

        # Find tickets still missing request type
        keys_to_enrich = [
            i.get("key", "") for i in issues
            if i.get("key") and not (
                i.get("fields", {}).get("customfield_10010") or {}
            ).get("requestType")
        ]
        if not keys_to_enrich:
            logger.info("All issues already have request type data, no enrichment needed")
            return

        logger.info("Enriching %d issues with request type data via JSM API", len(keys_to_enrich))

        rt_map: dict[str, dict] = {}

        import threading
        _thread_local = threading.local()

        def _get_session() -> requests.Session:
            """Thread-local session to avoid sharing a Session across threads."""
            if not hasattr(_thread_local, "session"):
                s = requests.Session()
                s.auth = self.session.auth
                s.headers.update(dict(self.session.headers))
                _thread_local.session = s
            return _thread_local.session

        def _fetch_rt(key: str) -> tuple[str, dict | None]:
            for attempt in range(3):
                try:
                    sess = _get_session()
                    url = f"{self.base_url}/rest/servicedeskapi/request/{key}?expand=requestType"
                    resp = sess.get(url, timeout=30)
                    if resp.status_code == 200:
                        data = resp.json()
                        rt = data.get("requestType")
                        if rt and rt.get("name"):
                            return key, rt
                    return key, None
                except Exception:
                    if attempt < 2:
                        import time
                        time.sleep(1)
                        # Reset session on connection errors
                        _thread_local.session = requests.Session()
                        _thread_local.session.auth = self.session.auth
                        _thread_local.session.headers.update(dict(self.session.headers))
                    continue
            return key, None

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_rt, k): k for k in keys_to_enrich}
            done_count = 0
            for future in as_completed(futures):
                key, rt = future.result()
                if rt:
                    rt_map[key] = rt
                done_count += 1
                if done_count % 500 == 0:
                    logger.info(
                        "Enrichment progress: %d/%d done (%d found)",
                        done_count, len(keys_to_enrich), len(rt_map),
                    )

        # Inject into issue fields as customfield_10010
        enriched = 0
        for issue in issues:
            key = issue.get("key", "")
            if key in rt_map:
                fields = issue.setdefault("fields", {})
                fields["customfield_10010"] = {"requestType": rt_map[key]}
                enriched += 1

        logger.info("Enriched %d/%d issues with request type data", enriched, len(keys_to_enrich))

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
        """Change request type via PUT /rest/api/3/issue/{key} using customfield_11102.

        The value must be the request type ID as a string (e.g. "122").
        """
        url = f"{self.base_url}/rest/api/3/issue/{key}"
        payload = {"fields": {"customfield_11102": str(request_type_id)}}
        resp = self.session.put(url, json=payload)
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
