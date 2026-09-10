"""Delegated Microsoft Graph calls for Teams retention: read channel content
and delete aged messages/replies/attachments. Every call here uses a
delegated access token — Graph has no supported application-permission path
for deleting channel messages."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MAX_RETRIES = 3


class RetentionGraphError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _request(method: str, url: str, access_token: str, **kwargs: Any) -> requests.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = None
    for attempt in range(_MAX_RETRIES):
        resp = requests.request(method, url, headers=headers, timeout=(10, 30), **kwargs)
        if resp.status_code != 429:
            return resp
        if attempt == _MAX_RETRIES - 1:
            return resp
        retry_after = int(resp.headers.get("Retry-After") or (2 ** attempt))
        time.sleep(retry_after)
    return resp  # type: ignore[return-value]


def _get_all_pages(url: str, access_token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_url: str | None = url
    while next_url:
        resp = _request("GET", next_url, access_token)
        if not resp.ok:
            raise RetentionGraphError(
                f"Graph GET {next_url} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
            )
        payload = resp.json()
        items.extend(payload.get("value") or [])
        next_url = payload.get("@odata.nextLink")
    return items


def list_teams(access_token: str) -> list[dict[str, Any]]:
    raw = _get_all_pages(f"{_GRAPH_BASE}/teams", access_token)
    return [{"id": t["id"], "name": t.get("displayName", "")} for t in raw]


def list_channels(access_token: str, team_id: str) -> list[dict[str, Any]]:
    raw = _get_all_pages(f"{_GRAPH_BASE}/teams/{team_id}/channels", access_token)
    return [{"id": c["id"], "name": c.get("displayName", "")} for c in raw]


def _message_summary(raw: dict[str, Any]) -> dict[str, Any]:
    attachments = [
        {"id": a.get("id", ""), "content_url": a.get("contentUrl", "")}
        for a in (raw.get("attachments") or [])
        if a.get("contentType") == "reference" and a.get("contentUrl")
    ]
    from_user = (raw.get("from") or {}).get("user") or {}
    return {
        "id": raw["id"],
        "created_at": raw.get("createdDateTime", ""),
        "sender_or_author": from_user.get("displayName", ""),
        "attachments": attachments,
    }


def _is_older_than(raw: dict[str, Any], cutoff: datetime) -> bool:
    created = raw.get("createdDateTime")
    if not created:
        return False
    return datetime.fromisoformat(created.replace("Z", "+00:00")) < cutoff


def list_messages_older_than(
    access_token: str, team_id: str, channel_id: str, cutoff: datetime,
) -> list[dict[str, Any]]:
    raw = _get_all_pages(f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages", access_token)
    return [_message_summary(m) for m in raw if _is_older_than(m, cutoff)]


def list_replies_older_than(
    access_token: str, team_id: str, channel_id: str, message_id: str, cutoff: datetime,
) -> list[dict[str, Any]]:
    raw = _get_all_pages(
        f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies", access_token,
    )
    replies = [_message_summary(r) for r in raw if _is_older_than(r, cutoff)]
    for reply in replies:
        reply["parent_id"] = message_id
    return replies


def delete_message(access_token: str, team_id: str, channel_id: str, message_id: str) -> None:
    url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages/{message_id}/softDelete"
    resp = _request("POST", url, access_token)
    if not resp.ok:
        raise RetentionGraphError(
            f"Delete message {message_id} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
        )


def delete_reply(access_token: str, team_id: str, channel_id: str, message_id: str, reply_id: str) -> None:
    url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies/{reply_id}/softDelete"
    resp = _request("POST", url, access_token)
    if not resp.ok:
        raise RetentionGraphError(
            f"Delete reply {reply_id} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
        )


def resolve_team_site_id(access_token: str, team_id: str) -> str:
    resp = _request("GET", f"{_GRAPH_BASE}/groups/{team_id}/sites/root?$select=id", access_token)
    if not resp.ok:
        raise RetentionGraphError(
            f"Resolve site for team {team_id} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
        )
    return resp.json()["id"]


def delete_drive_item(access_token: str, site_id: str, drive_item_id: str) -> None:
    url = f"{_GRAPH_BASE}/sites/{site_id}/drive/items/{drive_item_id}"
    resp = _request("DELETE", url, access_token)
    if not resp.ok and resp.status_code != 404:
        raise RetentionGraphError(
            f"Delete drive item {drive_item_id} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
        )
