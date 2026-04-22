"""Daily security digest service — sends a Teams message summarizing the prior 24h of Defender Agent activity."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import SECURITY_DIGEST_TEAMS_WEBHOOK, SECURITY_DIGEST_HOUR, OLLAMA_SECURITY_MODEL
from defender_agent_store import defender_agent_store

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _get_24h_stats() -> dict[str, Any]:
    """Aggregate Defender Agent decision stats for the last 24 hours."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    decisions, _ = defender_agent_store.list_decisions(limit=1000)
    recent = [d for d in decisions if (d.get("executed_at") or "") >= since]

    t1 = sum(1 for d in recent if d.get("decision") == "execute")
    t2 = sum(1 for d in recent if d.get("decision") == "queue")
    t3 = sum(1 for d in recent if d.get("decision") == "recommend")
    skips = sum(1 for d in recent if d.get("decision") == "skip")
    ai_fallback = sum(1 for d in recent if "AI fallback" in (d.get("reason") or ""))
    unresolved_t3 = sum(
        1 for d in decisions
        if d.get("decision") == "recommend" and not d.get("human_approved") and not d.get("cancelled")
    )

    cat_counts: dict[str, int] = {}
    entity_counts: dict[str, int] = {}
    for d in recent:
        cat = d.get("alert_category") or "Unknown"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for e in (d.get("entities") or []):
            name = e.get("name") or e.get("id") or ""
            if name:
                entity_counts[name] = entity_counts.get(name, 0) + 1

    top_categories = sorted(cat_counts, key=lambda k: -cat_counts[k])[:3]
    top_entities = sorted(entity_counts, key=lambda k: -entity_counts[k])[:3]

    return {
        "total": len(recent),
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "skips": skips,
        "ai_fallback": ai_fallback,
        "unresolved_t3": unresolved_t3,
        "top_categories": top_categories,
        "top_entities": top_entities,
    }


def _send_teams_digest(webhook_url: str) -> None:
    from ai_client import generate_security_digest
    config = defender_agent_store.get_security_runtime_config()
    model_id = config.get("ollama_model") or OLLAMA_SECURITY_MODEL

    stats = _get_24h_stats()
    narrative = generate_security_digest(stats, model_id)
    if not narrative:
        narrative = (
            f"- T1 (immediate): {stats['t1']}  T2 (queued): {stats['t2']}  "
            f"T3 (pending approval): {stats['t3']}  Skipped: {stats['skips']}\n"
            f"- Unresolved T3 approvals: {stats['unresolved_t3']}\n"
            f"- AI fallback classifications: {stats['ai_fallback']}"
        )

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"🛡️ Security Digest — {date_str}",
                            "weight": "bolder",
                            "size": "medium",
                        },
                        {
                            "type": "TextBlock",
                            "text": narrative,
                            "wrap": True,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "T1 (immediate)", "value": str(stats["t1"])},
                                {"title": "T2 (queued)", "value": str(stats["t2"])},
                                {"title": "T3 (pending approval)", "value": str(stats["t3"])},
                                {"title": "Skipped", "value": str(stats["skips"])},
                                {"title": "Unresolved T3", "value": str(stats["unresolved_t3"])},
                                {"title": "AI fallback", "value": str(stats["ai_fallback"])},
                            ],
                        },
                    ],
                },
            }
        ],
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("Security digest sent to Teams (%d decisions in last 24h)", stats["total"])
    except Exception as exc:
        logger.warning("Security digest Teams send failed: %s", exc)


async def _run_digest_loop() -> None:
    assert _stop_event is not None
    logger.info("Security digest service started (fires daily at %02d:00 UTC)", SECURITY_DIGEST_HOUR)
    while not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        next_fire = now.replace(hour=SECURITY_DIGEST_HOUR, minute=0, second=0, microsecond=0)
        if next_fire <= now:
            next_fire += timedelta(days=1)
        wait_seconds = (next_fire - now).total_seconds()
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=wait_seconds)
            break  # stop requested
        except asyncio.TimeoutError:
            pass  # time to fire

        if not SECURITY_DIGEST_TEAMS_WEBHOOK:
            logger.debug("Security digest: no SECURITY_DIGEST_TEAMS_WEBHOOK configured, skipping")
            continue

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _send_teams_digest, SECURITY_DIGEST_TEAMS_WEBHOOK)
        except Exception:
            logger.exception("Security digest send error")


async def start_worker() -> None:
    global _worker_task, _stop_event
    if _worker_task and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_run_digest_loop())


async def stop_worker() -> None:
    global _worker_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except (asyncio.CancelledError, Exception):
            pass
        _worker_task = None
