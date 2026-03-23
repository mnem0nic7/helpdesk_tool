"""Azure alert rule evaluation engine and background delivery loop."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from azure_alert_store import azure_alert_store
from email_service import send_email

logger = logging.getLogger(__name__)

_THROTTLE_MINUTES: dict[str, int] = {
    "immediate": 10,
    "hourly": 50,
    "daily": 20 * 60,
    "weekly": 140 * 60,
}

TRIGGER_LABELS: dict[str, str] = {
    "cost_threshold": "Cost threshold exceeded",
    "cost_spike": "Cost spike detected",
    "advisor_savings": "Advisor savings available",
    "vm_deallocated": "VMs deallocated",
    "vm_no_reservation": "VMs without reservation",
    "new_guest_users": "New guest users added",
    "accounts_disabled": "Accounts disabled",
    "stale_accounts": "Stale accounts (no password change)",
    "resource_count_exceeded": "Resource count exceeded",
    "resource_untagged": "Untagged resources",
}

TRIGGER_SCHEMA: dict[str, dict[str, Any]] = {
    "cost": {
        "cost_threshold": {"period": "monthly", "threshold_usd": 5000.0},
        "cost_spike": {"spike_pct": 20},
        "advisor_savings": {"min_monthly_savings_usd": 100.0},
    },
    "vms": {
        "vm_deallocated": {"min_days": 7},
        "vm_no_reservation": {},
    },
    "identity": {
        "new_guest_users": {},
        "accounts_disabled": {},
        "stale_accounts": {"min_days": 90},
    },
    "resources": {
        "resource_count_exceeded": {"resource_type": "", "threshold": 100},
        "resource_untagged": {"required_tags": []},
    },
}

# Snapshot → dataset key mapping for freshness checks
_SNAPSHOT_DATASET: dict[str, str] = {
    "cost_summary": "cost",
    "cost_trend": "cost",
    "advisor": "cost",
    "resources": "inventory",
    "reservations": "inventory",
    "users": "directory",
}


# ── Staleness check ───────────────────────────────────────────────────────────

def _snapshot_fresh(snapshot_name: str) -> bool:
    """Return True if the backing dataset was refreshed within 2× its interval."""
    try:
        from azure_cache import azure_cache
        dataset_key = _SNAPSHOT_DATASET.get(snapshot_name)
        if not dataset_key:
            return False
        status = azure_cache.status()
        for ds in status.get("datasets", []):
            if ds.get("key") == dataset_key:
                last_refresh = ds.get("last_refresh")
                interval = ds.get("interval_minutes", 60)
                if not last_refresh:
                    return False
                age = datetime.now(timezone.utc) - datetime.fromisoformat(
                    str(last_refresh).replace("Z", "+00:00")
                )
                return age < timedelta(minutes=int(interval) * 2)
        return False
    except Exception:
        return False


def _get_snapshot(name: str) -> Any:
    from azure_cache import azure_cache
    return azure_cache._snapshot(name)  # noqa: SLF001


# ── Cost evaluators ───────────────────────────────────────────────────────────

def evaluate_cost_threshold(
    trend: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    if not trend:
        return []
    period = config.get("period", "monthly")
    threshold = float(config.get("threshold_usd", 5000))
    rows = trend[-7:] if period == "weekly" else trend
    total = sum(float(r.get("cost", 0)) for r in rows)
    currency = trend[-1].get("currency", "USD") if trend else "USD"
    if total > threshold:
        return [{"period": period, "total_cost": round(total, 2), "currency": currency, "threshold_usd": threshold}]
    return []


def evaluate_cost_spike(
    trend: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    spike_pct = float(config.get("spike_pct", 20))
    # Need at least: today (partial, excluded) + yesterday + 2 baseline days = 4 rows
    if len(trend) < 4:
        return []
    ordered = sorted(trend, key=lambda r: r.get("date", ""))
    completed = ordered[:-1]  # exclude today's partial row
    if len(completed) < 3:
        return []
    yesterday = completed[-1]
    baseline_rows = completed[-7:-1]  # up to 6 rows before yesterday
    if len(baseline_rows) < 2:
        return []
    avg = sum(float(r.get("cost", 0)) for r in baseline_rows) / len(baseline_rows)
    yesterday_cost = float(yesterday.get("cost", 0))
    if avg == 0:
        return []
    pct_change = ((yesterday_cost - avg) / avg) * 100
    if pct_change >= spike_pct:
        return [{
            "date": yesterday.get("date"),
            "yesterday_cost": round(yesterday_cost, 2),
            "baseline_avg": round(avg, 2),
            "pct_change": round(pct_change, 1),
            "currency": yesterday.get("currency", "USD"),
        }]
    return []


def evaluate_advisor_savings(
    items: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    min_savings = float(config.get("min_monthly_savings_usd", 100))
    return [i for i in items if float(i.get("monthly_savings", 0)) >= min_savings]


# ── VM evaluators ─────────────────────────────────────────────────────────────

def evaluate_vm_deallocated(
    resources: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    min_days = int(config.get("min_days", 7))
    now = datetime.now(timezone.utc)
    deallocated_ids: set[str] = set()
    matched: list[dict[str, Any]] = []

    for res in resources:
        if res.get("resource_type", "").lower() != "microsoft.compute/virtualmachines":
            continue
        state = str(res.get("state", "")).lower()
        if "deallocated" not in state:
            continue
        vm_id = res["id"]
        deallocated_ids.add(vm_id)
        first_seen = azure_alert_store.get_vm_first_seen_deallocated(vm_id)
        if first_seen is None:
            azure_alert_store.set_vm_first_seen_deallocated(vm_id, now.isoformat())
            continue
        first_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
        days_off = (now - first_dt).days
        if days_off >= min_days:
            matched.append({
                "id": vm_id,
                "name": res.get("name", ""),
                "location": res.get("location", ""),
                "resource_group": res.get("resource_group", ""),
                "days_deallocated": days_off,
            })

    azure_alert_store.purge_vm_states(deallocated_ids)
    return matched


def evaluate_vm_no_reservation(
    resources: list[dict[str, Any]],
    reservations: list[dict[str, Any]],
    _config: dict[str, Any],
) -> list[dict[str, Any]]:
    # Build coverage map: (sku, location) → remaining count
    coverage: dict[tuple[str, str], int] = {}
    for res in reservations:
        key = (str(res.get("sku", "")).lower(), str(res.get("location", "")).lower())
        coverage[key] = coverage.get(key, 0) + int(res.get("quantity", 0))

    unmatched: list[dict[str, Any]] = []
    for res in resources:
        if res.get("resource_type", "").lower() != "microsoft.compute/virtualmachines":
            continue
        state = str(res.get("state", "")).lower()
        if "running" not in state:
            continue
        key = (str(res.get("vm_size", "")).lower(), str(res.get("location", "")).lower())
        if coverage.get(key, 0) > 0:
            coverage[key] -= 1
        else:
            unmatched.append({
                "id": res["id"],
                "name": res.get("name", ""),
                "size": res.get("vm_size", ""),
                "location": res.get("location", ""),
                "resource_group": res.get("resource_group", ""),
            })
    return unmatched


# ── Identity evaluators ───────────────────────────────────────────────────────

def evaluate_new_guest_users(
    users: list[dict[str, Any]], last_run: str | None
) -> list[dict[str, Any]]:
    matched = []
    for u in users:
        extra = u.get("extra", {})
        if extra.get("user_type") != "Guest":
            continue
        created = extra.get("created_datetime", "")
        if not created:
            continue
        if last_run is None:
            matched.append(u)
            continue
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            if created_dt > last_dt:
                matched.append(u)
        except ValueError:
            continue
    return matched


def evaluate_accounts_disabled(
    users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matched = []
    has_baseline = False
    for u in users:
        user_id = u.get("id", "")
        if not user_id:
            continue
        current_enabled = bool(u.get("enabled"))
        stored = azure_alert_store.get_user_state(user_id)
        if stored is not None:
            has_baseline = True
            if stored["enabled"] and not current_enabled:
                matched.append({
                    "id": user_id,
                    "display_name": u.get("display_name", ""),
                    "principal_name": u.get("principal_name", ""),
                    "department": u.get("extra", {}).get("department", ""),
                })
        azure_alert_store.upsert_user_state(user_id, current_enabled)
    # On first run return empty — no baseline yet
    if not has_baseline:
        return []
    return matched


def evaluate_stale_accounts(
    users: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    min_days = int(config.get("min_days", 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_days)
    matched = []
    for u in users:
        if not u.get("enabled"):
            continue
        extra = u.get("extra", {})
        if extra.get("on_prem_sync") == "true":
            continue  # on-prem managed passwords — exclude
        last_pw = extra.get("last_password_change", "")
        if not last_pw:
            continue  # insufficient data
        try:
            pw_dt = datetime.fromisoformat(last_pw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if pw_dt < cutoff:
            matched.append({
                "id": u.get("id", ""),
                "display_name": u.get("display_name", ""),
                "principal_name": u.get("principal_name", ""),
                "department": extra.get("department", ""),
                "last_password_change": last_pw,
                "days_since_change": (datetime.now(timezone.utc) - pw_dt).days,
            })
    return matched


# ── Resource evaluators ───────────────────────────────────────────────────────

def evaluate_resource_count_exceeded(
    resources: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    target_type = str(config.get("resource_type", "")).lower()
    threshold = int(config.get("threshold", 100))
    if not target_type:
        return []
    count = sum(1 for r in resources if r.get("resource_type", "").lower() == target_type)
    if count > threshold:
        return [{"resource_type": target_type, "count": count, "threshold": threshold}]
    return []


def evaluate_resource_untagged(
    resources: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    required_tags = [t.lower() for t in (config.get("required_tags") or [])]
    if not required_tags:
        return []
    matched = []
    for r in resources:
        tags = {k.lower(): v for k, v in (r.get("tags") or {}).items()}
        missing = [t for t in required_tags if t not in tags]
        if missing:
            matched.append({
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "resource_type": r.get("resource_type", ""),
                "resource_group": r.get("resource_group", ""),
                "missing_tags": missing,
            })
    return matched


# ── Rule dispatch ─────────────────────────────────────────────────────────────

def _evaluate_rule(rule: dict[str, Any]) -> list[dict[str, Any]]:
    trigger = rule["trigger_type"]
    config = rule.get("trigger_config") or {}
    last_run = rule.get("last_run")

    if trigger == "cost_threshold":
        if not _snapshot_fresh("cost_trend"):
            logger.warning("Skipping cost_threshold — cost data stale or unavailable")
            return []
        return evaluate_cost_threshold(_get_snapshot("cost_trend") or [], config)

    if trigger == "cost_spike":
        if not _snapshot_fresh("cost_trend"):
            return []
        return evaluate_cost_spike(_get_snapshot("cost_trend") or [], config)

    if trigger == "advisor_savings":
        if not _snapshot_fresh("advisor"):
            return []
        return evaluate_advisor_savings(_get_snapshot("advisor") or [], config)

    if trigger == "vm_deallocated":
        if not _snapshot_fresh("resources"):
            return []
        return evaluate_vm_deallocated(_get_snapshot("resources") or [], config)

    if trigger == "vm_no_reservation":
        if not _snapshot_fresh("resources"):
            return []
        return evaluate_vm_no_reservation(
            _get_snapshot("resources") or [],
            _get_snapshot("reservations") or [],
            config,
        )

    if trigger == "new_guest_users":
        if not _snapshot_fresh("users"):
            return []
        return evaluate_new_guest_users(_get_snapshot("users") or [], last_run)

    if trigger == "accounts_disabled":
        if not _snapshot_fresh("users"):
            return []
        return evaluate_accounts_disabled(_get_snapshot("users") or [])

    if trigger == "stale_accounts":
        if not _snapshot_fresh("users"):
            return []
        return evaluate_stale_accounts(_get_snapshot("users") or [], config)

    if trigger == "resource_count_exceeded":
        if not _snapshot_fresh("resources"):
            return []
        return evaluate_resource_count_exceeded(_get_snapshot("resources") or [], config)

    if trigger == "resource_untagged":
        if not _snapshot_fresh("resources"):
            return []
        return evaluate_resource_untagged(_get_snapshot("resources") or [], config)

    logger.warning("Unknown trigger type: %s", trigger)
    return []


# ── Email rendering ───────────────────────────────────────────────────────────

def _render_email_html(rule: dict[str, Any], items: list[dict[str, Any]]) -> str:
    trigger = rule["trigger_type"]
    label = TRIGGER_LABELS.get(trigger, trigger)
    custom_msg = rule.get("custom_message", "")

    def row(cells: list[str]) -> str:
        return "<tr>" + "".join(
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{c}</td>"
            for c in cells
        ) + "</tr>"

    if trigger == "cost_threshold" and items:
        headers = ["Period / Threshold", "Total cost"]
        rows_html = row([
            f"{items[0].get('period', '').title()} / ${items[0].get('threshold_usd', '')}",
            f"${items[0].get('total_cost', ''):.2f} {items[0].get('currency', '')}",
        ])
    elif trigger == "cost_spike" and items:
        headers = ["Date", "Yesterday cost", "Baseline avg", "Change"]
        rows_html = row([
            str(items[0].get("date", "")),
            f"${items[0].get('yesterday_cost', ''):.2f}",
            f"${items[0].get('baseline_avg', ''):.2f}",
            f"{items[0].get('pct_change', '')}%",
        ])
    elif trigger == "advisor_savings":
        headers = ["Recommendation", "Monthly savings", "Subscription"]
        rows_html = "".join(
            row([i.get("title", ""), f"${i.get('monthly_savings', 0):.2f}", i.get("subscription_name", "")])
            for i in items[:20]
        )
    elif trigger in ("vm_deallocated", "vm_no_reservation"):
        if trigger == "vm_deallocated":
            headers = ["VM Name", "Location", "Resource Group", "Days Off"]
            rows_html = "".join(
                row([i.get("name", ""), i.get("location", ""), i.get("resource_group", ""), str(i.get("days_deallocated", ""))])
                for i in items[:50]
            )
        else:
            headers = ["VM Name", "Size", "Location", "Resource Group"]
            rows_html = "".join(
                row([i.get("name", ""), i.get("size", ""), i.get("location", ""), i.get("resource_group", "")])
                for i in items[:50]
            )
    elif trigger in ("new_guest_users", "accounts_disabled", "stale_accounts"):
        headers = ["Name", "UPN", "Department"]
        rows_html = "".join(
            row([i.get("display_name", ""), i.get("principal_name", ""), i.get("department", "")])
            for i in items[:50]
        )
    else:
        headers = ["Name", "Type", "Resource Group"]
        rows_html = "".join(
            row([i.get("name", ""), i.get("resource_type", ""), i.get("resource_group", "")])
            for i in items[:50]
        )

    header_cells = "".join(
        f"<th style='padding:6px 10px;text-align:left;color:#fff'>{h}</th>"
        for h in headers
    )
    overflow = (
        f"<p style='color:#666;font-size:12px'>Showing 50 of {len(items)} items.</p>"
        if len(items) > 50 else ""
    )
    custom_section = (
        f"<p style='margin:12px 0'>{custom_msg.replace(chr(10), '<br>')}</p>"
        if custom_msg else ""
    )

    return f"""
    <div style='font-family:sans-serif;max-width:700px'>
      <div style='background:#1e3a5f;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0'>
        <h2 style='margin:0;font-size:18px'>{label}</h2>
        <p style='margin:4px 0 0;font-size:13px;opacity:.85'>{rule['name']} · {len(items)} item{"s" if len(items) != 1 else ""}</p>
      </div>
      <div style='border:1px solid #ddd;border-top:none;padding:16px 20px;border-radius:0 0 8px 8px'>
        {custom_section}
        <table style='width:100%;border-collapse:collapse;font-size:13px'>
          <thead style='background:#1e3a5f'><tr>{header_cells}</tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        {overflow}
      </div>
    </div>
    """


# ── Teams delivery ────────────────────────────────────────────────────────────

def _build_teams_card(rule: dict[str, Any], items: list[dict[str, Any]], site_origin: str) -> dict[str, Any]:
    label = TRIGGER_LABELS.get(rule["trigger_type"], rule["trigger_type"])
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary_text = f"{len(items)} item{'s' if len(items) != 1 else ''} matched"
    if items and "name" in items[0]:
        names = ", ".join(i.get("name", "") for i in items[:3])
        if len(items) > 3:
            names += f" and {len(items) - 3} more"
        summary_text += f": {names}"

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "text": f"\U0001f514 Azure Alert \u2014 {rule['name']}", "weight": "Bolder", "size": "Medium"},
                    {"type": "TextBlock", "text": f"{label} \u00b7 {now_str}", "isSubtle": True, "spacing": "None"},
                    {"type": "TextBlock", "text": summary_text, "wrap": True, "spacing": "Small"},
                ],
                "actions": [
                    {"type": "Action.OpenUrl", "title": "View in Dashboard", "url": f"{site_origin}/alerts"},
                    {"type": "Action.OpenUrl", "title": "Open Azure Portal", "url": "https://portal.azure.com"},
                ],
            },
        }],
    }


async def _post_teams(webhook_url: str, card: dict[str, Any]) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(webhook_url, json=card)
        if not resp.is_success:
            raise RuntimeError(f"Teams webhook returned {resp.status_code}: {resp.text[:200]}")
    return True


async def _deliver(rule: dict[str, Any], items: list[dict[str, Any]]) -> tuple[str, str | None]:
    """Send email and/or Teams. Returns (status, error_str | None)."""
    try:
        from config import CORS_ORIGIN
        site_origin = CORS_ORIGIN or "https://it-app.movedocs.com"
    except ImportError:
        site_origin = "https://it-app.movedocs.com"

    label = TRIGGER_LABELS.get(rule["trigger_type"], rule["trigger_type"])
    count = len(items)
    subject_template = rule.get("custom_subject") or "[Azure Alert] {rule_name}: {match_count} {trigger_label}"
    subject = (
        subject_template
        .replace("{rule_name}", rule["name"])
        .replace("{match_count}", str(count))
        .replace("{trigger_label}", label)
    )
    html = _render_email_html(rule, items)
    recipients_str = rule.get("recipients", "")
    teams_url = rule.get("teams_webhook_url", "")

    email_to = [e.strip() for e in recipients_str.split(",") if e.strip()] if recipients_str else []
    tasks: list[Any] = []
    if email_to:
        tasks.append(send_email(email_to, subject, html))
    if teams_url:
        card = _build_teams_card(rule, items, site_origin)
        tasks.append(_post_teams(teams_url, card))

    if not tasks:
        return "failed", "No delivery channels configured"

    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors: list[str] = []
    successes = 0
    for result in results:
        if isinstance(result, Exception):
            errors.append(str(result))
        elif result is False:
            errors.append("Delivery returned False")
        else:
            successes += 1

    if not errors:
        return "sent", None
    if successes > 0:
        return "partial", "; ".join(errors)
    return "failed", "; ".join(errors)


# ── Schedule logic ────────────────────────────────────────────────────────────

def _should_run(rule: dict[str, Any]) -> bool:
    if not rule.get("enabled"):
        return False
    last_run = rule.get("last_run")
    if not last_run:
        return True
    try:
        last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
    except ValueError:
        return True
    freq = rule.get("frequency", "daily")
    throttle = _THROTTLE_MINUTES.get(freq, 60)
    if (datetime.now(timezone.utc) - last_dt) < timedelta(minutes=throttle):
        return False
    if freq in ("daily", "weekly"):
        now = datetime.now(timezone.utc)
        schedule_time = rule.get("schedule_time", "09:00")
        try:
            hour, minute = (int(x) for x in schedule_time.split(":"))
        except ValueError:
            hour, minute = 9, 0
        if now.hour != hour:
            return False
        schedule_days = rule.get("schedule_days", "0,1,2,3,4")
        try:
            allowed_days = {int(d) for d in schedule_days.split(",") if d.strip()}
        except ValueError:
            allowed_days = {0, 1, 2, 3, 4}
        if now.weekday() not in allowed_days:
            return False
    return True


async def _run_rule(rule: dict[str, Any]) -> None:
    rule_id = rule["id"]
    try:
        items = _evaluate_rule(rule)
    except Exception:
        logger.exception("Evaluation failed for rule %s (%s)", rule_id, rule.get("name"))
        azure_alert_store.update_last_run(rule_id)
        return

    azure_alert_store.update_last_run(rule_id, last_sent=False)

    if not items:
        return  # zero-match — no history row written

    recipients_str = rule.get("recipients", "")
    status, error = await _deliver(rule, items)
    azure_alert_store.record_history(
        rule_id, rule["name"], rule["trigger_type"],
        recipients_str, len(items), items, status, error,
    )
    if status != "failed":
        azure_alert_store.update_last_run(rule_id, last_sent=True)


def run_due_rules() -> None:
    """Synchronous entry point called from executor thread."""
    rules = azure_alert_store.list_rules()
    due = [r for r in rules if _should_run(r)]
    if not due:
        return
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(asyncio.gather(*[_run_rule(r) for r in due]))
    finally:
        loop.close()


# ── Background loop ───────────────────────────────────────────────────────────

_bg_task: asyncio.Task[None] | None = None


async def start_azure_alert_loop() -> None:
    global _bg_task
    if _bg_task and not _bg_task.done():
        return
    _bg_task = asyncio.get_running_loop().create_task(_loop())


async def stop_azure_alert_loop() -> None:
    global _bg_task
    if not _bg_task:
        return
    _bg_task.cancel()
    try:
        await _bg_task
    except asyncio.CancelledError:
        pass
    _bg_task = None


async def _loop() -> None:
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, run_due_rules)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Azure alert loop iteration failed")
        await asyncio.sleep(60)


# ── Chat parse ────────────────────────────────────────────────────────────────

_CHAT_SYSTEM_PROMPT = """
You are an Azure monitoring assistant. Parse the user's natural-language request into a structured JSON alert rule.

Valid domains and trigger types:
- cost: cost_threshold (config: period="monthly"|"weekly", threshold_usd=float), cost_spike (config: spike_pct=int), advisor_savings (config: min_monthly_savings_usd=float)
- vms: vm_deallocated (config: min_days=int), vm_no_reservation (config: {})
- identity: new_guest_users (config: {}), accounts_disabled (config: {}), stale_accounts (config: min_days=int)
- resources: resource_count_exceeded (config: resource_type=str, threshold=int), resource_untagged (config: required_tags=[str])

Valid frequencies: immediate, hourly, daily, weekly
schedule_time: HH:MM UTC (default "09:00")
schedule_days: comma-separated 0=Mon..6=Sun (default "0,1,2,3,4")

Return ONLY a JSON object in one of these two forms:
Success: {"parsed": true, "name": str, "domain": str, "trigger_type": str, "trigger_config": {}, "frequency": str, "schedule_time": str, "schedule_days": str, "recipients": "", "teams_webhook_url": "", "summary": "one-line human description"}
Failure: {"parsed": false, "error": "brief explanation of what could not be parsed"}

Do not include any text outside the JSON object.
""".strip()


def parse_azure_alert_rule(message: str) -> dict[str, Any]:
    """Call AI to parse a natural-language alert description. Returns raw dict."""
    from ai_client import _call_anthropic, _call_ollama, _call_openai, get_available_models  # noqa: PLC0415

    models = get_available_models()
    if not models:
        return {"parsed": False, "error": "No AI models configured"}

    model = models[0]
    try:
        if model.provider == "openai":
            raw = _call_openai(model.id, _CHAT_SYSTEM_PROMPT, message)
        elif model.provider == "ollama":
            raw = _call_ollama(model.id, _CHAT_SYSTEM_PROMPT, message)
        else:
            raw = _call_anthropic(model.id, _CHAT_SYSTEM_PROMPT, message)
        return json.loads(raw.strip())
    except (json.JSONDecodeError, Exception) as exc:
        return {"parsed": False, "error": str(exc)}
