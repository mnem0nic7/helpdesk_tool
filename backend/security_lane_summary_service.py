"""AI-08: Security lane AI summary service.

Leader-only background service that regenerates AI triage summaries for each
of the 9 security review lanes on a configurable interval (default 60 minutes).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from config import OLLAMA_SECURITY_MODEL, SECURITY_LANE_SUMMARY_INTERVAL_MINUTES

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None

# Synthetic system session used for session-gated builders (device_compliance,
# conditional_access_tracker) — read-only, no actual user identity needed.
_SYSTEM_SESSION: dict[str, Any] = {
    "auth_provider": "entra",
    "is_admin": True,
    "email": "system@security-lane-summary",
    "display_name": "System",
}

# The 9 lanes covered by AI-08.  The summary_mode field tells the extractor
# which data shape to expect from the builder.
_LANES: list[dict[str, Any]] = [
    {"key": "access-review",             "label": "Privileged Access Review",        "mode": "access_review"},
    {"key": "conditional-access-tracker","label": "Conditional Access Tracker",       "mode": "conditional_access"},
    {"key": "break-glass-validation",    "label": "Break-Glass Validation",           "mode": "break_glass"},
    {"key": "identity-review",           "label": "Identity Review",                  "mode": "workspace"},
    {"key": "app-hygiene",               "label": "Application Hygiene",              "mode": "app_hygiene"},
    {"key": "user-review",               "label": "User Review",                      "mode": "workspace"},
    {"key": "guest-access-review",       "label": "Guest Access Review",              "mode": "workspace"},
    {"key": "account-health",            "label": "Account Health",                   "mode": "workspace"},
    {"key": "device-compliance",         "label": "Device Compliance",                "mode": "device_compliance"},
]


# ---------------------------------------------------------------------------
# Per-lane data extraction helpers
# ---------------------------------------------------------------------------

def _extract_access_review() -> tuple[str, int, str, list[dict[str, Any]]]:
    from security_access_review import build_security_access_review
    data = build_security_access_review()
    attention = len(data.flagged_principals)
    top = [
        {"name": p.display_name or p.principal_id, "flags": p.flags[:3]}
        for p in data.flagged_principals[:10]
    ]
    status = "critical" if attention >= 5 else ("warning" if attention > 0 else "healthy")
    return status, attention, f"{attention} flagged principals", top


def _extract_conditional_access() -> tuple[str, int, str, list[dict[str, Any]]]:
    from security_conditional_access_tracker import build_security_conditional_access_tracker
    data = build_security_conditional_access_tracker(_SYSTEM_SESSION)
    changes = len(data.changes)
    top = [
        {"policy": c.policy_display_name, "change": c.change_type, "at": c.changed_at}
        for c in data.changes[:10]
    ]
    status = "warning" if changes > 0 else "healthy"
    return status, changes, f"{changes} policy changes", top


def _extract_break_glass() -> tuple[str, int, str, list[dict[str, Any]]]:
    from security_break_glass_validation import build_security_break_glass_validation
    data = build_security_break_glass_validation()
    problems = [a for a in data.accounts if a.status in ("critical", "warning")]
    attention = len(problems)
    top = [
        {"name": a.display_name or a.account_id, "status": a.status, "flags": a.flags[:3]}
        for a in problems[:10]
    ]
    status = "critical" if any(a.status == "critical" for a in problems) else ("warning" if problems else "healthy")
    return status, attention, f"{attention} break-glass issues", top


def _extract_workspace_lane(lane_key: str) -> tuple[str, int, str, list[dict[str, Any]]]:
    from security_workspace_summary import build_security_workspace_summary
    summary = build_security_workspace_summary(_SYSTEM_SESSION)
    lane = next((la for la in summary.lanes if la.lane_key == lane_key), None)
    if lane is None:
        return "info", 0, "No data", []
    top: list[dict[str, Any]] = [{"label": lane.attention_label, "count": lane.attention_count}]
    return lane.status, lane.attention_count, lane.attention_label, top


def _extract_app_hygiene() -> tuple[str, int, str, list[dict[str, Any]]]:
    from security_application_hygiene import build_security_application_hygiene
    data = build_security_application_hygiene()
    flagged = len(data.flagged_apps)
    top = [
        {"name": a.display_name, "status": a.status, "flags": a.flags[:3]}
        for a in data.flagged_apps[:10]
    ]
    status = "critical" if any(a.status == "critical" for a in data.flagged_apps) else ("warning" if flagged else "healthy")
    return status, flagged, f"{flagged} flagged apps", top


def _extract_device_compliance() -> tuple[str, int, str, list[dict[str, Any]]]:
    from security_device_compliance import build_security_device_compliance_review
    data = build_security_device_compliance_review(_SYSTEM_SESSION)
    non_compliant = [d for d in data.devices if d.compliance_state != "compliant"]
    attention = len(non_compliant)
    top = [
        {"name": d.device_name or d.device_id, "state": d.compliance_state, "os": d.operating_system}
        for d in non_compliant[:10]
    ]
    status = "critical" if attention >= 10 else ("warning" if attention > 0 else "healthy")
    return status, attention, f"{attention} non-compliant devices", top


def _get_lane_data(lane: dict[str, Any]) -> tuple[str, int, str, list[dict[str, Any]]]:
    mode = lane["mode"]
    key = lane["key"]
    try:
        if mode == "access_review":
            return _extract_access_review()
        if mode == "conditional_access":
            return _extract_conditional_access()
        if mode == "break_glass":
            return _extract_break_glass()
        if mode == "workspace":
            return _extract_workspace_lane(key)
        if mode == "app_hygiene":
            return _extract_app_hygiene()
        if mode == "device_compliance":
            return _extract_device_compliance()
    except Exception as exc:
        logger.warning("Lane summary data extraction failed for %s: %s", key, exc)
    return "unavailable", 0, "Data unavailable", []


# ---------------------------------------------------------------------------
# DB persistence (mirrors defender_agent_store pattern — direct Postgres/SQLite)
# ---------------------------------------------------------------------------

def _upsert_summary(
    lane_key: str,
    narrative: str,
    teaser: str,
    bullets: list[str],
    model_id: str,
) -> None:
    from defender_agent_store import defender_agent_store
    generated_at = datetime.now(timezone.utc).isoformat()
    bullets_json = json.dumps(bullets, ensure_ascii=False)
    store = defender_agent_store
    p = store._placeholder()  # %s or ?
    with store._conn() as conn:
        if store._use_postgres:
            conn.execute(
                f"""INSERT INTO security_lane_ai_summaries
                    (lane_key, narrative, teaser, bullets_json, generated_at, model_used)
                    VALUES ({p},{p},{p},{p},{p},{p})
                    ON CONFLICT (lane_key) DO UPDATE SET
                      narrative=EXCLUDED.narrative, teaser=EXCLUDED.teaser,
                      bullets_json=EXCLUDED.bullets_json, generated_at=EXCLUDED.generated_at,
                      model_used=EXCLUDED.model_used""",
                (lane_key, narrative, teaser, bullets_json, generated_at, model_id),
            )
        else:
            conn.execute(
                f"""INSERT OR REPLACE INTO security_lane_ai_summaries
                    (lane_key, narrative, teaser, bullets_json, generated_at, model_used)
                    VALUES ({p},{p},{p},{p},{p},{p})""",
                (lane_key, narrative, teaser, bullets_json, generated_at, model_id),
            )


def get_all_lane_summaries() -> list[dict[str, Any]]:
    """Return all stored lane summaries as plain dicts."""
    from defender_agent_store import defender_agent_store as das
    try:
        with das._conn() as conn:
            rows = conn.execute(
                "SELECT lane_key, narrative, teaser, bullets_json, generated_at, model_used "
                "FROM security_lane_ai_summaries ORDER BY lane_key"
            ).fetchall()
        result = []
        for row in rows:
            if hasattr(row, "keys"):
                r = dict(row)
            else:
                keys = ("lane_key", "narrative", "teaser", "bullets_json", "generated_at", "model_used")
                r = dict(zip(keys, row))
            try:
                r["bullets"] = json.loads(r.get("bullets_json") or "[]")
            except Exception:
                r["bullets"] = []
            result.append(r)
        return result
    except Exception as exc:
        logger.warning("get_all_lane_summaries failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Per-lane summary generation (called from background thread)
# ---------------------------------------------------------------------------

def generate_lane_summary_sync(lane: dict[str, Any], model_id: str) -> None:
    """Collect lane data, call the AI, persist result. Runs in a thread executor."""
    from ai_client import generate_lane_summary as _gen
    key = lane["key"]
    label = lane["label"]
    logger.debug("Lane summary: generating for %s", key)
    status, attention_count, attention_label, top_items = _get_lane_data(lane)
    if status == "unavailable":
        logger.debug("Lane summary: skipping %s — data unavailable", key)
        return
    result = _gen(key, label, status, attention_count, attention_label, top_items, model_id)
    if not result:
        return
    _upsert_summary(
        key,
        result.get("narrative", ""),
        result.get("teaser", ""),
        result.get("bullets", []),
        model_id,
    )
    logger.info("Lane summary: generated %s (status=%s attention=%d)", key, status, attention_count)


# ---------------------------------------------------------------------------
# Async service loop
# ---------------------------------------------------------------------------

async def _run_summary_loop() -> None:
    assert _stop_event is not None
    interval = SECURITY_LANE_SUMMARY_INTERVAL_MINUTES * 60
    logger.info(
        "Security lane summary service started — %d lanes, interval=%dm",
        len(_LANES),
        SECURITY_LANE_SUMMARY_INTERVAL_MINUTES,
    )
    # Fire immediately on first start, then wait for interval
    first_run = True
    while not _stop_event.is_set():
        if not first_run:
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=float(interval))
                break  # stop requested
            except asyncio.TimeoutError:
                pass

        first_run = False
        from defender_agent_store import defender_agent_store as das
        config = das.get_security_runtime_config()
        model_id = config.get("ollama_model") or OLLAMA_SECURITY_MODEL

        loop = asyncio.get_event_loop()
        for lane in _LANES:
            if _stop_event.is_set():
                break
            try:
                await loop.run_in_executor(None, generate_lane_summary_sync, lane, model_id)
            except Exception:
                logger.exception("Lane summary error for %s", lane["key"])


async def start_worker() -> None:
    global _worker_task, _stop_event
    if _worker_task and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_run_summary_loop())


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
