"""Jira REST API v3 client for the OIT Helpdesk Dashboard."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from config import JIRA_EMAIL, JIRA_API_TOKEN, JIRA_BASE_URL
from request_type import extract_request_type_name_from_fields, has_request_type

# Validate Jira issue keys to prevent path traversal / SSRF
_JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
_NAME_TOKEN_RE = re.compile(r"[a-z0-9]+")


def validate_jira_key(key: str) -> str:
    """Validate that a string looks like a Jira issue key (e.g. OIT-1234)."""
    if not _JIRA_KEY_RE.match(key):
        raise ValueError(f"Invalid Jira key format: {key!r}")
    return key

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

    # Default timeout for all Jira API requests (connect, read) in seconds
    _TIMEOUT = (10, 30)

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
        self._thread_local = threading.local()

    def _get_thread_session(self) -> requests.Session:
        """Return a per-thread session for concurrent Jira access.

        ``requests.Session`` is not safe to share across worker threads.
        Master report changelog prefetch uses a thread pool, so each thread
        needs its own session with the same auth and headers.
        """
        if not hasattr(self._thread_local, "session"):
            session = requests.Session()
            session.auth = self.session.auth
            session.headers.update(dict(self.session.headers))
            self._thread_local.session = session
        return self._thread_local.session

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        """Like raise_for_status() but includes the Jira response body in the error."""
        if resp.ok:
            return
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:500]
        raise requests.HTTPError(
            f"{resp.status_code} {resp.reason} — Jira error: {body}",
            response=resp,
        )

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

        resp = self.session.post(url, json=payload, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def search_all(
        self,
        jql: str,
        fields: list[str] | None = None,
        progress_callback: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through ALL results for a JQL query using nextPageToken.

        Returns a flat list of issue dicts.
        """
        url = f"{self.base_url}/rest/api/3/search/jql"
        all_issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        request_fields = fields or FIELDS
        known_total: int | None = None  # Cache total from first response

        while True:
            payload: dict[str, Any] = {
                "jql": jql,
                "maxResults": 100,
                "fields": request_fields,
            }
            if next_page_token:
                payload["nextPageToken"] = next_page_token

            resp = self.session.post(url, json=payload, timeout=self._TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            issues = data.get("issues", [])
            all_issues.extend(issues)

            # Report progress if callback provided
            if "total" in data:
                known_total = data["total"]
            if progress_callback:
                total = known_total if known_total is not None else len(all_issues)
                progress_callback("fetching", len(all_issues), total)

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

            logger.debug(
                "Fetched %d issues so far (nextPageToken: %s)",
                len(all_issues),
                next_page_token[:20] if next_page_token else "None",
            )

        logger.info("search_all complete: %d issues for JQL: %s", len(all_issues), jql)

        # Fetch full comments for tickets where the search API truncated them
        self._backfill_comments(all_issues, progress_callback=progress_callback)

        return all_issues

    # ------------------------------------------------------------------
    # Comment backfill
    # ------------------------------------------------------------------

    def _backfill_comments(self, issues: list[dict[str, Any]], progress_callback: Any | None = None) -> None:
        """Fetch all comments for issues where the search API truncated them.

        The Jira search API limits comments to ~5 per issue. For tickets
        with more comments, fetch the full list via the issue comment endpoint.
        """
        truncated = []
        for iss in issues:
            comment_obj = iss.get("fields", {}).get("comment", {})
            total = comment_obj.get("total", 0)
            returned = len(comment_obj.get("comments", []))
            if total > returned:
                truncated.append(iss)

        if not truncated:
            return

        logger.info("Backfilling comments for %d issues (truncated by search API)", len(truncated))
        if progress_callback:
            progress_callback("backfilling", 0, len(truncated))

        for idx, iss in enumerate(truncated):
            key = iss.get("key", "")
            try:
                url = f"{self.base_url}/rest/api/3/issue/{key}/comment"
                all_comments: list[dict[str, Any]] = []
                start_at = 0
                while True:
                    resp = self.session.get(url, params={"startAt": start_at, "maxResults": 100}, timeout=self._TIMEOUT)
                    resp.raise_for_status()
                    data = resp.json()
                    all_comments.extend(data.get("comments", []))
                    if start_at + data.get("maxResults", 100) >= data.get("total", 0):
                        break
                    start_at += data.get("maxResults", 100)

                iss["fields"]["comment"] = {
                    "comments": all_comments,
                    "total": len(all_comments),
                    "maxResults": len(all_comments),
                    "startAt": 0,
                }
            except Exception:
                logger.warning("Failed to backfill comments for %s", key, exc_info=True)
            if progress_callback:
                progress_callback("backfilling", idx + 1, len(truncated))

    def get_issue_changelog_page(
        self,
        key: str,
        *,
        start_at: int = 0,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Fetch one page of Jira changelog history for an issue."""
        validate_jira_key(key)
        url = f"{self.base_url}/rest/api/3/issue/{key}/changelog"
        resp = self._get_thread_session().get(
            url,
            params={"startAt": start_at, "maxResults": max_results},
            timeout=self._TIMEOUT,
        )
        self._raise_for_status(resp)
        return resp.json()

    def get_issue_changelog_all(self, key: str) -> list[dict[str, Any]]:
        """Fetch all changelog histories for an issue."""
        histories: list[dict[str, Any]] = []
        start_at = 0
        while True:
            data = self.get_issue_changelog_page(key, start_at=start_at, max_results=100)
            page_histories = data.get("values") or data.get("histories") or []
            histories.extend(page_histories)
            page_size = int(data.get("maxResults") or 100)
            total = int(data.get("total") or len(page_histories))
            start_at += page_size
            if start_at >= total or not page_histories:
                break
        return histories

    def get_request_comments(self, key: str) -> list[dict[str, Any]]:
        """GET all JSM request comments, preserving public/internal visibility."""
        validate_jira_key(key)
        url = f"{self.base_url}/rest/servicedeskapi/request/{key}/comment"
        comments: list[dict[str, Any]] = []
        start = 0

        while True:
            resp = self.session.get(
                url,
                params={"start": start, "limit": 100, "public": "true", "internal": "true"},
                timeout=self._TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            values = data.get("values", [])
            comments.extend(values)
            if data.get("isLastPage", True):
                break
            start += len(values)

        return comments

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
                cached_name = extract_request_type_name_from_fields(cached.get("fields", {}))
                if cached_name:
                    issue.setdefault("fields", {})["customfield_10010"] = {
                        "requestType": {"name": cached_name}
                    }
                    carried += 1
            if carried:
                logger.info("Carried forward %d request types from cache", carried)

        # Find tickets still missing request type
        keys_to_enrich = [
            i.get("key", "") for i in issues
            if i.get("key") and not has_request_type(i.get("fields", {}))
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
        validate_jira_key(key)
        url = f"{self.base_url}/rest/api/3/issue/{key}"
        resp = self.session.get(url, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_transitions(self, key: str) -> list[dict[str, Any]]:
        """GET /rest/api/3/issue/{key}/transitions"""
        validate_jira_key(key)
        url = f"{self.base_url}/rest/api/3/issue/{key}/transitions"
        resp = self.session.get(url, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("transitions", [])

    def transition_issue(self, key: str, transition_id: str) -> None:
        """POST /rest/api/3/issue/{key}/transitions"""
        validate_jira_key(key)
        url = f"{self.base_url}/rest/api/3/issue/{key}/transitions"
        payload = {"transition": {"id": transition_id}}
        resp = self.session.post(url, json=payload, timeout=self._TIMEOUT)
        self._raise_for_status(resp)

    def assign_issue(self, key: str, account_id: str | None) -> None:
        """PUT /rest/api/3/issue/{key}/assignee"""
        validate_jira_key(key)
        url = f"{self.base_url}/rest/api/3/issue/{key}/assignee"
        payload = {"accountId": account_id}
        resp = self.session.put(url, json=payload, timeout=self._TIMEOUT)
        self._raise_for_status(resp)

    def update_issue_fields(self, key: str, fields: dict[str, Any]) -> None:
        """PUT /rest/api/3/issue/{key} with partial field updates."""
        validate_jira_key(key)
        url = f"{self.base_url}/rest/api/3/issue/{key}"
        payload = {"fields": fields}
        logger.debug("update_issue_fields %s: %s", key, fields)
        resp = self.session.put(url, json=payload, timeout=self._TIMEOUT)
        self._raise_for_status(resp)

    def update_priority(self, key: str, priority_name: str) -> None:
        """PUT /rest/api/3/issue/{key} to change priority."""
        self.update_issue_fields(key, {"priority": {"name": priority_name}})

    def update_reporter(self, key: str, account_id: str) -> None:
        """PUT /rest/api/3/issue/{key} to change reporter."""
        self.update_issue_fields(key, {"reporter": {"id": account_id}})

    def update_components(self, key: str, component_names: list[str]) -> None:
        """PUT /rest/api/3/issue/{key} to change issue components."""
        self.update_issue_fields(
            key,
            {"components": [{"name": name} for name in component_names]},
        )

    def update_work_category(self, key: str, work_category: str | None) -> None:
        """PUT /rest/api/3/issue/{key} to change the work category field."""
        self.update_issue_fields(key, {"customfield_11239": work_category})

    @staticmethod
    def _plain_text_to_adf(text: str) -> dict[str, Any]:
        """Convert plain text into a minimal Atlassian Document Format payload."""
        paragraphs: list[dict[str, Any]] = []
        for block in text.split("\n\n"):
            lines = block.splitlines() or [""]
            content: list[dict[str, Any]] = []
            for index, line in enumerate(lines):
                if line:
                    content.append({"type": "text", "text": line})
                if index < len(lines) - 1:
                    content.append({"type": "hardBreak"})
            paragraphs.append({"type": "paragraph", "content": content})
        return {"version": 1, "type": "doc", "content": paragraphs or [{"type": "paragraph", "content": []}]}

    def update_summary(self, key: str, summary: str) -> None:
        """Update the issue summary."""
        self.update_issue_fields(key, {"summary": summary})

    def update_description(self, key: str, description: str) -> None:
        """Update the issue description from plain text."""
        self.update_issue_fields(key, {"description": self._plain_text_to_adf(description)})

    def create_issue(
        self,
        *,
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        description: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /rest/api/3/issue to create a Jira issue."""
        project = project_key.strip().upper()
        if not project:
            raise ValueError("project_key is required")
        summary_text = summary.strip()
        if not summary_text:
            raise ValueError("summary is required")
        issue_type_text = issue_type.strip() or "Task"
        payload_fields: dict[str, Any] = {
            "project": {"key": project},
            "summary": summary_text,
            "issuetype": {"name": issue_type_text},
        }
        if description.strip():
            payload_fields["description"] = self._plain_text_to_adf(description)
        if labels:
            payload_fields["labels"] = [label.strip() for label in labels if label and label.strip()]

        url = f"{self.base_url}/rest/api/3/issue"
        resp = self.session.post(url, json={"fields": payload_fields}, timeout=self._TIMEOUT)
        self._raise_for_status(resp)
        return resp.json()

    def add_comment(self, key: str, body_text: str) -> dict[str, Any]:
        """POST /rest/api/3/issue/{key}/comment using ADF format."""
        validate_jira_key(key)
        url = f"{self.base_url}/rest/api/3/issue/{key}/comment"
        payload = {"body": self._plain_text_to_adf(body_text)}
        resp = self.session.post(url, json=payload, timeout=self._TIMEOUT)
        self._raise_for_status(resp)
        return resp.json()

    def add_request_comment(self, key: str, body_text: str, public: bool = False) -> dict[str, Any]:
        """POST a JSM request comment as an internal note or customer reply."""
        validate_jira_key(key)
        url = f"{self.base_url}/rest/servicedeskapi/request/{key}/comment"
        payload = {"body": body_text, "public": public}
        resp = self.session.post(url, json=payload, timeout=self._TIMEOUT)
        self._raise_for_status(resp)
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
            resp = self.session.get(url, params={"start": start, "limit": 100}, timeout=self._TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            all_types.extend(data.get("values", []))
            if data.get("isLastPage", True):
                break
            start += len(data.get("values", []))
        return all_types

    def get_service_desks(self) -> list[dict[str, Any]]:
        """GET /rest/servicedeskapi/servicedesk for all service desks."""
        url = f"{self.base_url}/rest/servicedeskapi/servicedesk"
        resp = self.session.get(url, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("values", [])

    def get_service_desk_id_for_project(self, project: str) -> str | None:
        """Return the service desk ID for a project key, if one exists."""
        for desk in self.get_service_desks():
            if str(desk.get("projectKey", "")).upper() == project.upper():
                return str(desk.get("id", ""))
        return None

    def set_request_type(self, key: str, request_type_id: str) -> None:
        """Change request type via PUT /rest/api/3/issue/{key} using customfield_11102.

        The value must be the request type ID as a string (e.g. "122").
        """
        self.update_issue_fields(key, {"customfield_11102": str(request_type_id)})

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_users_assignable(self, project: str) -> list[dict[str, Any]]:
        """GET /rest/api/3/user/assignable/search?project={project}"""
        url = f"{self.base_url}/rest/api/3/user/assignable/search"
        params = {"project": project}
        resp = self.session.get(url, params=params, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def search_users(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        """GET /rest/api/3/user/search?query=... for broad user lookup."""
        url = f"{self.base_url}/rest/api/3/user/search"
        params = {"query": query, "maxResults": max_results}
        resp = self.session.get(url, params=params, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _display_name_tokens(value: str) -> list[str]:
        """Normalize a display name into lowercase alphanumeric tokens."""
        return _NAME_TOKEN_RE.findall((value or "").strip().lower())

    @classmethod
    def _matches_with_optional_middle_names(cls, target: str, candidate: str) -> bool:
        """Return True when a candidate adds only middle-name tokens.

        Examples:
        - "Raza Abidi" -> "Raza Ali Abidi" : True
        - "Raza Abidi" -> "Mohammed Raza Abidi" : False
        - "Raza Abidi" -> "Raza Abidi Khan" : False
        """
        target_tokens = cls._display_name_tokens(target)
        candidate_tokens = cls._display_name_tokens(candidate)
        if len(target_tokens) < 2 or len(candidate_tokens) <= len(target_tokens):
            return False
        if target_tokens[0] != candidate_tokens[0] or target_tokens[-1] != candidate_tokens[-1]:
            return False

        index = 0
        for token in candidate_tokens:
            if index < len(target_tokens) and token == target_tokens[index]:
                index += 1
        return index == len(target_tokens)

    def find_user_account_id(self, display_name: str) -> str | None:
        """Return a unique Jira accountId for a display name.

        Prefers an exact displayName match. If none exists, allows a single
        candidate whose display name only adds middle-name tokens, such as
        "Raza Abidi" matching "Raza Ali Abidi".
        """
        target = display_name.strip().lower()
        if not target:
            return None
        users = self.search_users(display_name)
        candidates = [
            user
            for user in users
            if user.get("accountId") and user.get("active") is not False
        ]

        exact_matches = [
            user.get("accountId", "")
            for user in candidates
            if user.get("displayName", "").strip().lower() == target
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            return None

        middle_name_matches = [
            user.get("accountId", "")
            for user in candidates
            if self._matches_with_optional_middle_names(display_name, user.get("displayName", ""))
        ]
        if len(middle_name_matches) == 1:
            return middle_name_matches[0]
        return None

    def get_user(self, account_id: str) -> dict[str, Any]:
        """GET /rest/api/3/user?accountId=... for a specific Jira user."""
        url = f"{self.base_url}/rest/api/3/user"
        resp = self.session.get(url, params={"accountId": account_id}, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_priorities(self) -> list[dict[str, Any]]:
        """GET /rest/api/3/priority — returns all configured priorities."""
        url = f"{self.base_url}/rest/api/3/priority"
        resp = self.session.get(url, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json()
