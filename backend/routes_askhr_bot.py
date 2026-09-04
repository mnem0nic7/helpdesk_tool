"""FastAPI routes for the AskHR/Benefits bot."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from askhr_bot_job import MAILBOXES, askhr_bot_job
from auth import require_admin

router = APIRouter(prefix="/api/askhr-bot", tags=["askhr-bot"])


class PatchSettingsRequest(BaseModel):
    enabled: bool | None = None
    poll_interval_seconds: int | None = None
    lookback_minutes: int | None = None
    domain_refresh_interval_seconds: int | None = None


def _last_run(mailbox: str) -> dict[str, Any] | None:
    ph = askhr_bot_job._placeholder()
    with askhr_bot_job._conn() as conn:
        row = conn.execute(
            f"SELECT id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count "
            f"FROM askhr_bot_runs WHERE mailbox = {ph} ORDER BY run_started_at DESC LIMIT 1",
            (mailbox,),
        ).fetchone()
    return dict(row) if row is not None else None


def _status_payload() -> dict[str, Any]:
    settings = askhr_bot_job._get_settings()
    return {
        **settings,
        "last_runs": {mailbox: _last_run(mailbox) for mailbox in MAILBOXES},
    }


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_status() -> dict[str, Any]:
    return _status_payload()


@router.get("/runs", dependencies=[Depends(require_admin)])
async def get_runs(
    mailbox: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    ph = askhr_bot_job._placeholder()
    columns = "id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count"
    with askhr_bot_job._conn() as conn:
        if mailbox:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM askhr_bot_runs WHERE mailbox = {ph}", (mailbox,)
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT {columns} FROM askhr_bot_runs WHERE mailbox = {ph} "
                f"ORDER BY run_started_at DESC LIMIT {ph} OFFSET {ph}",
                (mailbox, limit, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM askhr_bot_runs").fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT {columns} FROM askhr_bot_runs ORDER BY run_started_at DESC LIMIT {ph} OFFSET {ph}",
                (limit, offset),
            ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/messages", dependencies=[Depends(require_admin)])
async def get_messages(
    mailbox: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    ph = askhr_bot_job._placeholder()
    columns = (
        "internet_message_id, mailbox, graph_message_id, subject, sender_email, received_at, "
        "status, jira_issue_key, error, processed_at"
    )
    clauses = []
    params: list[Any] = []
    if mailbox:
        clauses.append(f"mailbox = {ph}")
        params.append(mailbox)
    if status:
        clauses.append(f"status = {ph}")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with askhr_bot_job._conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS cnt FROM askhr_bot_messages {where}", params).fetchone()["cnt"]
        rows = conn.execute(
            f"SELECT {columns} FROM askhr_bot_messages {where} "
            f"ORDER BY received_at DESC LIMIT {ph} OFFSET {ph}",
            (*params, limit, offset),
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.patch("/settings")
async def patch_settings(
    body: PatchSettingsRequest,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated_by = user.get("email") or user.get("name") or "unknown"
    askhr_bot_job._update_settings(updated_by=updated_by, **updates)
    return _status_payload()


@router.post("/reporter-mode/reset")
async def reset_reporter_mode(user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    updated_by = user.get("email") or user.get("name") or "unknown"
    askhr_bot_job._update_settings(reporter_mode="unset", updated_by=updated_by)
    return _status_payload()


@router.post("/messages/{internet_message_id}/retry", dependencies=[Depends(require_admin)])
async def retry_message(
    internet_message_id: str,
    # Required, not optional: a Message-ID alone does not identify a row --
    # the same email can be addressed to both AskHR@ and Benefits@, each with
    # its own ticket. Forcing the caller to name the mailbox is the only way a
    # retry can never operate on the other mailbox's copy.
    mailbox: str = Query(..., description="askhr | benefits"),
) -> dict[str, Any]:
    if mailbox not in MAILBOXES:
        raise HTTPException(status_code=400, detail=f"Unknown mailbox: {mailbox}")
    ph = askhr_bot_job._placeholder()
    with askhr_bot_job._conn() as conn:
        row = conn.execute(
            f"SELECT mailbox, graph_message_id, subject, sender_email, received_at, jira_issue_key "
            f"FROM askhr_bot_messages WHERE mailbox = {ph} AND internet_message_id = {ph}",
            (mailbox, internet_message_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")

    existing_issue_key = row["jira_issue_key"]
    try:
        # askhr_bot_messages only ever stores metadata, never the body, so a
        # retry has to re-fetch the live message from Graph -- a stale
        # in-DB stand-in (previously an empty body) would silently create a
        # ticket with none of the sender's actual content.
        message = askhr_bot_job._fetch_message_from_graph(row["mailbox"], row["graph_message_id"])
        status, issue_key, error = askhr_bot_job._create_or_attach_ticket(
            row["mailbox"], message, existing_issue_key=existing_issue_key
        )
    except Exception as exc:
        message = {
            "internet_message_id": internet_message_id,
            "graph_message_id": row["graph_message_id"],
            "subject": row["subject"],
            "sender_email": row["sender_email"],
            "received_at": row["received_at"],
        }
        status, issue_key, error = "failed", existing_issue_key, str(exc)
    with askhr_bot_job._conn() as conn:
        askhr_bot_job._record_message(
            mailbox=row["mailbox"], message=message, status=status,
            jira_issue_key=issue_key, error=error, conn=conn,
        )
    return {
        "internet_message_id": internet_message_id,
        "mailbox": row["mailbox"],
        "status": status,
        "jira_issue_key": issue_key,
        "error": error,
    }
