"""Send emails via Microsoft Graph API using the shared mailbox."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET

logger = logging.getLogger(__name__)

GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

# Default sender — can be overridden per call
DEFAULT_SENDER = "it-ai@librasolutionsgroup.com"

_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0}


async def _get_access_token() -> str:
    """Acquire an app-only access token using client credentials."""
    import time

    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    url = TOKEN_URL.format(tenant=ENTRA_TENANT_ID)
    data = {
        "client_id": ENTRA_CLIENT_ID,
        "client_secret": ENTRA_CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=data)
        resp.raise_for_status()
        body = resp.json()

    _token_cache["access_token"] = body["access_token"]
    _token_cache["expires_at"] = time.time() + body.get("expires_in", 3600)
    return _token_cache["access_token"]


async def send_email(
    to: list[str],
    subject: str,
    html_body: str,
    sender: str = DEFAULT_SENDER,
    cc: list[str] | None = None,
) -> bool:
    """Send an email from the shared mailbox via Graph API.

    Returns True on success, False on failure.
    """
    if not ENTRA_TENANT_ID or not ENTRA_CLIENT_ID or not ENTRA_CLIENT_SECRET:
        logger.warning("Email send skipped — Entra ID credentials not configured")
        return False

    try:
        token = await _get_access_token()
    except Exception:
        logger.exception("Failed to acquire Graph API token")
        return False

    url = GRAPH_SEND_URL.format(sender=sender)

    message: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
    }
    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

    payload = {"message": message, "saveToSentItems": True}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=30.0,
            )
        if resp.status_code == 202:
            logger.info("Email sent to %s: %s", to, subject)
            return True
        else:
            logger.error("Graph API error %s: %s", resp.status_code, resp.text[:500])
            return False
    except Exception:
        logger.exception("Failed to send email via Graph API")
        return False
