# Azure Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Azure Alerts tab that monitors cost, VM, identity, and resource conditions, notifying via email and Teams webhooks, with both a chat-based and form-based rule builder.

**Architecture:** Parallel to the existing Jira alert system — three new backend files (`azure_alert_store.py`, `azure_alert_engine.py`, `routes_azure_alerts.py`) plus one frontend page (`AzureAlertsPage.tsx`). No changes to existing alert infrastructure. SQLite persistence in `azure_alerts.db`.

**Tech Stack:** Python 3.12, FastAPI, SQLite, httpx (Teams webhook), React 18, TypeScript, Tailwind CSS 4, React Query, `ai_client.py` (OpenAI/Anthropic) for chat-parse.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `backend/models.py` |
| Create | `backend/azure_alert_store.py` |
| Create | `backend/azure_alert_engine.py` |
| Create | `backend/routes_azure_alerts.py` |
| Modify | `backend/main.py` |
| Create | `backend/tests/test_azure_alert_store.py` |
| Create | `backend/tests/test_azure_alert_engine.py` |
| Create | `backend/tests/test_routes_azure_alerts.py` |
| Modify | `frontend/src/lib/api.ts` |
| Create | `frontend/src/pages/AzureAlertsPage.tsx` |
| Modify | `frontend/src/App.tsx` |
| Modify | `frontend/src/components/Layout.tsx` |

---

## Task 1: Pydantic Models

**Files:**
- Modify: `backend/models.py`

- [ ] Add imports at top of `models.py` — `from typing import Literal` if not present

- [ ] Append these models to `models.py`:

```python
# ── Azure Alerts ─────────────────────────────────────────────────────────────

class AzureAlertRuleCreate(BaseModel):
    name: str
    domain: Literal["cost", "vms", "identity", "resources"]
    trigger_type: str
    trigger_config: dict[str, Any] = {}
    frequency: Literal["immediate", "hourly", "daily", "weekly"]
    schedule_time: str = "09:00"        # HH:MM, always UTC
    schedule_days: str = "0,1,2,3,4"   # comma-separated 0=Mon..6=Sun
    recipients: str = ""                # comma-separated emails
    teams_webhook_url: str = ""
    custom_subject: str = ""
    custom_message: str = ""

class AzureAlertRuleUpdate(AzureAlertRuleCreate):
    pass

class AzureAlertRuleResponse(AzureAlertRuleCreate):
    id: str
    enabled: bool
    last_run: str | None = None
    last_sent: str | None = None
    created_at: str
    updated_at: str

class AzureAlertTestResponse(BaseModel):
    match_count: int
    sample_items: list[dict[str, Any]]

class AzureAlertHistoryItem(BaseModel):
    id: str
    rule_id: str
    rule_name: str
    trigger_type: str
    sent_at: str
    recipients: str
    match_count: int
    match_summary: dict[str, Any]
    status: str
    error: str | None = None

class AzureChatParseRequest(BaseModel):
    message: str

class AzureChatParseResponse(BaseModel):
    parsed: bool
    rule: AzureAlertRuleCreate | None = None
    summary: str = ""
    error: str = ""
```

- [ ] Run from `backend/`: `python -c "from models import AzureAlertRuleCreate, AzureAlertRuleResponse, AzureAlertHistoryItem, AzureChatParseResponse; print('OK')`
  Expected: `OK`

- [ ] Commit: `git add backend/models.py && git commit -m "feat: add Azure alert Pydantic models"`

---

## Task 2: Alert Store

**Files:**
- Create: `backend/azure_alert_store.py`
- Create: `backend/tests/test_azure_alert_store.py`

- [ ] Write the failing test first:

```python
# backend/tests/test_azure_alert_store.py
from __future__ import annotations
import pytest
from azure_alert_store import AzureAlertStore

RULE = {
    "name": "Cost spike",
    "domain": "cost",
    "trigger_type": "cost_spike",
    "trigger_config": {"spike_pct": 20},
    "frequency": "daily",
    "recipients": "admin@example.com",
}

def test_create_and_get_rule(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    assert rule["id"]
    assert rule["name"] == "Cost spike"
    assert rule["enabled"] is True
    fetched = store.get_rule(rule["id"])
    assert fetched["domain"] == "cost"

def test_list_rules(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    store.create_rule(RULE)
    store.create_rule({**RULE, "name": "Rule 2"})
    assert len(store.list_rules()) == 2

def test_update_rule(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    updated = store.update_rule(rule["id"], {**RULE, "name": "Updated"})
    assert updated["name"] == "Updated"

def test_toggle_rule(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    assert rule["enabled"] is True
    toggled = store.toggle_rule(rule["id"])
    assert toggled["enabled"] is False

def test_delete_rule_cascades_history(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    store.record_history(rule["id"], rule["name"], "cost_spike", "admin@x.com", 1, [], "sent", None)
    assert len(store.get_history()) == 1
    store.delete_rule(rule["id"])
    assert store.get_rule(rule["id"]) is None
    assert len(store.get_history()) == 0  # cascade

def test_update_last_run(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    rule = store.create_rule(RULE)
    store.update_last_run(rule["id"])
    updated = store.get_rule(rule["id"])
    assert updated["last_run"] is not None

def test_get_history_filters_by_rule(tmp_path):
    store = AzureAlertStore(str(tmp_path / "alerts.db"))
    r1 = store.create_rule(RULE)
    r2 = store.create_rule({**RULE, "name": "Rule 2"})
    store.record_history(r1["id"], r1["name"], "cost_spike", "a@x.com", 2, [], "sent", None)
    store.record_history(r2["id"], r2["name"], "cost_threshold", "b@x.com", 0, [], "sent", None)
    assert len(store.get_history(rule_id=r1["id"])) == 1
```

- [ ] Run: `cd backend && python -m pytest tests/test_azure_alert_store.py -v`
  Expected: all FAIL with `ModuleNotFoundError: No module named 'azure_alert_store'`

- [ ] Create `backend/azure_alert_store.py`:

```python
"""SQLite-backed store for Azure alert rules, history, and state tables."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AzureAlertStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS azure_alert_rules (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL,
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    domain          TEXT NOT NULL,
                    trigger_type    TEXT NOT NULL,
                    trigger_config  TEXT NOT NULL DEFAULT '{}',
                    frequency       TEXT NOT NULL,
                    schedule_time   TEXT NOT NULL DEFAULT '09:00',
                    schedule_days   TEXT NOT NULL DEFAULT '0,1,2,3,4',
                    recipients      TEXT NOT NULL DEFAULT '',
                    teams_webhook_url TEXT NOT NULL DEFAULT '',
                    custom_subject  TEXT NOT NULL DEFAULT '',
                    custom_message  TEXT NOT NULL DEFAULT '',
                    last_run        TEXT,
                    last_sent       TEXT,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_azure_alert_rules_domain_enabled
                    ON azure_alert_rules (domain, enabled);
                CREATE TABLE IF NOT EXISTS azure_alert_history (
                    id              TEXT PRIMARY KEY,
                    rule_id         TEXT NOT NULL REFERENCES azure_alert_rules(id) ON DELETE CASCADE,
                    rule_name       TEXT NOT NULL,
                    trigger_type    TEXT NOT NULL,
                    sent_at         TEXT NOT NULL,
                    recipients      TEXT NOT NULL,
                    match_count     INTEGER NOT NULL DEFAULT 0,
                    match_summary   TEXT NOT NULL DEFAULT '{}',
                    status          TEXT NOT NULL,
                    error           TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_azure_alert_history_rule_sent
                    ON azure_alert_history (rule_id, sent_at);
                CREATE TABLE IF NOT EXISTS azure_alert_vm_states (
                    vm_id                   TEXT PRIMARY KEY,
                    first_seen_deallocated  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS azure_alert_user_states (
                    user_id     TEXT PRIMARY KEY,
                    enabled     INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)
            conn.commit()

    def _row_to_rule(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["trigger_config"] = json.loads(d.get("trigger_config") or "{}")
        d["enabled"] = bool(d["enabled"])
        return d

    def create_rule(self, data: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(uuid.uuid4())
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO azure_alert_rules
                   (id, name, enabled, domain, trigger_type, trigger_config,
                    frequency, schedule_time, schedule_days, recipients,
                    teams_webhook_url, custom_subject, custom_message,
                    last_run, last_sent, created_at, updated_at)
                   VALUES (?,?,1,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)""",
                (
                    rule_id, data["name"], data["domain"], data["trigger_type"],
                    json.dumps(data.get("trigger_config") or {}),
                    data.get("frequency", "daily"),
                    data.get("schedule_time", "09:00"),
                    data.get("schedule_days", "0,1,2,3,4"),
                    data.get("recipients", ""),
                    data.get("teams_webhook_url", ""),
                    data.get("custom_subject", ""),
                    data.get("custom_message", ""),
                    now, now,
                ),
            )
            conn.commit()
        return self.get_rule(rule_id)  # type: ignore[return-value]

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM azure_alert_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return self._row_to_rule(row) if row else None

    def list_rules(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM azure_alert_rules ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def update_rule(self, rule_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """UPDATE azure_alert_rules SET
                   name=?, domain=?, trigger_type=?, trigger_config=?,
                   frequency=?, schedule_time=?, schedule_days=?,
                   recipients=?, teams_webhook_url=?,
                   custom_subject=?, custom_message=?, updated_at=?
                   WHERE id=?""",
                (
                    data["name"], data["domain"], data["trigger_type"],
                    json.dumps(data.get("trigger_config") or {}),
                    data.get("frequency", "daily"),
                    data.get("schedule_time", "09:00"),
                    data.get("schedule_days", "0,1,2,3,4"),
                    data.get("recipients", ""),
                    data.get("teams_webhook_url", ""),
                    data.get("custom_subject", ""),
                    data.get("custom_message", ""),
                    now, rule_id,
                ),
            )
            conn.commit()
        return self.get_rule(rule_id)

    def toggle_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE azure_alert_rules SET enabled = 1 - enabled, updated_at = ? WHERE id = ?",
                (_now(), rule_id),
            )
            conn.commit()
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM azure_alert_rules WHERE id = ?", (rule_id,))
            conn.commit()

    def update_last_run(self, rule_id: str, last_sent: bool = False) -> None:
        now = _now()
        with self._conn() as conn:
            if last_sent:
                conn.execute(
                    "UPDATE azure_alert_rules SET last_run=?, last_sent=?, updated_at=? WHERE id=?",
                    (now, now, now, rule_id),
                )
            else:
                conn.execute(
                    "UPDATE azure_alert_rules SET last_run=?, updated_at=? WHERE id=?",
                    (now, now, rule_id),
                )
            conn.commit()

    def record_history(
        self,
        rule_id: str,
        rule_name: str,
        trigger_type: str,
        recipients: str,
        match_count: int,
        sample_items: list[dict[str, Any]],
        status: str,
        error: str | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO azure_alert_history
                   (id, rule_id, rule_name, trigger_type, sent_at, recipients,
                    match_count, match_summary, status, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), rule_id, rule_name, trigger_type,
                    _now(), recipients, match_count,
                    json.dumps({"items": sample_items[:10]}),
                    status, error,
                ),
            )
            conn.commit()

    def get_history(
        self, *, limit: int = 100, rule_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if rule_id:
                rows = conn.execute(
                    "SELECT * FROM azure_alert_history WHERE rule_id=? ORDER BY sent_at DESC LIMIT ?",
                    (rule_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM azure_alert_history ORDER BY sent_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["match_summary"] = json.loads(d.get("match_summary") or "{}")
            result.append(d)
        return result

    # ── State tables ──────────────────────────────────────────────────────────

    def get_vm_first_seen_deallocated(self, vm_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT first_seen_deallocated FROM azure_alert_vm_states WHERE vm_id=?",
                (vm_id,),
            ).fetchone()
        return row[0] if row else None

    def set_vm_first_seen_deallocated(self, vm_id: str, ts: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO azure_alert_vm_states (vm_id, first_seen_deallocated) VALUES (?,?)",
                (vm_id, ts),
            )
            conn.commit()

    def purge_vm_states(self, active_vm_ids: set[str]) -> None:
        """Remove tracking rows for VMs no longer deallocated."""
        with self._conn() as conn:
            rows = conn.execute("SELECT vm_id FROM azure_alert_vm_states").fetchall()
            stale = [r[0] for r in rows if r[0] not in active_vm_ids]
            for vm_id in stale:
                conn.execute("DELETE FROM azure_alert_vm_states WHERE vm_id=?", (vm_id,))
            conn.commit()

    def get_user_state(self, user_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled, recorded_at FROM azure_alert_user_states WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return {"enabled": bool(row[0]), "recorded_at": row[1]} if row else None

    def upsert_user_state(self, user_id: str, enabled: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO azure_alert_user_states (user_id, enabled, recorded_at)
                   VALUES (?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled, recorded_at=excluded.recorded_at""",
                (user_id, int(enabled), _now()),
            )
            conn.commit()


# Module-level singleton (path resolved at import time via config)
def _make_store() -> AzureAlertStore:
    from config import DATA_DIR
    import os
    return AzureAlertStore(os.path.join(DATA_DIR, "azure_alerts.db"))


azure_alert_store: AzureAlertStore = _make_store()
```

- [ ] Run: `cd backend && python -m pytest tests/test_azure_alert_store.py -v`
  Expected: all PASS

- [ ] Commit: `git add backend/azure_alert_store.py backend/tests/test_azure_alert_store.py && git commit -m "feat: add AzureAlertStore with SQLite persistence"`

---

## Task 3: Evaluators — Cost Domain

**Files:**
- Create: `backend/azure_alert_engine.py` (partial — evaluators only)
- Create: `backend/tests/test_azure_alert_engine.py` (partial)

- [ ] Write failing tests for cost evaluators:

```python
# backend/tests/test_azure_alert_engine.py
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta


def _make_trend(days: int, base_cost: float = 100.0) -> list[dict]:
    today = datetime.now(timezone.utc)
    return [
        {"date": (today - timedelta(days=days - i)).strftime("%Y-%m-%d"),
         "cost": base_cost, "currency": "USD"}
        for i in range(days)
    ]


def test_cost_threshold_monthly_matches(tmp_path):
    from azure_alert_engine import evaluate_cost_threshold
    trend = _make_trend(30, base_cost=400.0)  # 30 * 400 = 12000
    result = evaluate_cost_threshold(trend, {"period": "monthly", "threshold_usd": 10000})
    assert len(result) == 1
    assert result[0]["total_cost"] == pytest.approx(12000.0)

def test_cost_threshold_monthly_no_match(tmp_path):
    from azure_alert_engine import evaluate_cost_threshold
    trend = _make_trend(30, base_cost=10.0)  # 300 total
    result = evaluate_cost_threshold(trend, {"period": "monthly", "threshold_usd": 10000})
    assert result == []

def test_cost_threshold_weekly_uses_last_7(tmp_path):
    from azure_alert_engine import evaluate_cost_threshold
    # 30 days at 10/day, but only last 7 matter for weekly
    trend = _make_trend(30, base_cost=10.0)  # last 7 = 70
    result = evaluate_cost_threshold(trend, {"period": "weekly", "threshold_usd": 60})
    assert len(result) == 1

def test_cost_spike_detects_spike(tmp_path):
    from azure_alert_engine import evaluate_cost_spike
    # 6 baseline days at 100, yesterday at 200 (100% spike), today partial (excluded)
    today = datetime.now(timezone.utc)
    trend = [
        {"date": (today - timedelta(days=8 - i)).strftime("%Y-%m-%d"),
         "cost": 100.0, "currency": "USD"} for i in range(6)
    ]
    trend.append({"date": (today - timedelta(days=1)).strftime("%Y-%m-%d"), "cost": 200.0, "currency": "USD"})
    trend.append({"date": today.strftime("%Y-%m-%d"), "cost": 50.0, "currency": "USD"})  # partial, excluded
    result = evaluate_cost_spike(trend, {"spike_pct": 20})
    assert len(result) == 1
    assert result[0]["pct_change"] == pytest.approx(100.0)

def test_cost_spike_no_spike(tmp_path):
    from azure_alert_engine import evaluate_cost_spike
    trend = _make_trend(10, base_cost=100.0)
    result = evaluate_cost_spike(trend, {"spike_pct": 20})
    assert result == []

def test_cost_spike_insufficient_data(tmp_path):
    from azure_alert_engine import evaluate_cost_spike
    trend = _make_trend(2, base_cost=999.0)
    result = evaluate_cost_spike(trend, {"spike_pct": 20})
    assert result == []

def test_advisor_savings_filters_threshold(tmp_path):
    from azure_alert_engine import evaluate_advisor_savings
    items = [
        {"title": "Big saving", "monthly_savings": 500.0, "annual_savings": 6000.0, "currency": "USD", "description": "", "subscription_name": "Prod"},
        {"title": "Tiny saving", "monthly_savings": 10.0, "annual_savings": 120.0, "currency": "USD", "description": "", "subscription_name": "Dev"},
    ]
    result = evaluate_advisor_savings(items, {"min_monthly_savings_usd": 100.0})
    assert len(result) == 1
    assert result[0]["title"] == "Big saving"
```

- [ ] Run: `cd backend && python -m pytest tests/test_azure_alert_engine.py -v`
  Expected: FAIL with `ModuleNotFoundError`

- [ ] Create `backend/azure_alert_engine.py` with cost evaluators + stubs for other domains:

```python
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

_SNAPSHOT_DATASET: dict[str, str] = {
    "cost_summary": "cost",
    "cost_trend": "cost",
    "advisor": "cost",
    "resources": "inventory",
    "reservations": "inventory",
    "users": "directory",
}

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

# ── Staleness check ───────────────────────────────────────────────────────────

def _snapshot_fresh(snapshot_name: str) -> bool:
    """Return True if the backing dataset has been refreshed recently enough."""
    try:
        from azure_cache import azure_cache
        dataset_key = _SNAPSHOT_DATASET.get(snapshot_name)
        if not dataset_key:
            return False
        status = azure_cache.status()
        for ds in status.get("datasets", []):
            if ds.get("key") == dataset_key or ds.get("label", "").lower() == dataset_key:
                last_refresh = ds.get("last_refresh")
                interval = ds.get("interval_minutes", 60)
                if not last_refresh:
                    return False
                age = datetime.now(timezone.utc) - datetime.fromisoformat(
                    str(last_refresh).replace("Z", "+00:00")
                )
                return age < timedelta(minutes=interval * 2)
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
    # Need at least today (partial, excluded) + yesterday + 2 baseline days = 4 rows
    if len(trend) < 4:
        return []
    ordered = sorted(trend, key=lambda r: r.get("date", ""))
    # Exclude last row (today, partial)
    completed = ordered[:-1]
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
    return [
        item for item in items
        if float(item.get("monthly_savings", 0)) >= min_savings
    ]


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
    # Build coverage map: (sku, location) -> remaining count
    coverage: dict[tuple[str, str], int] = {}
    for res in reservations:
        key = (str(res.get("sku", "")).lower(), str(res.get("location", "")).lower())
        coverage[key] = coverage.get(key, 0) + int(res.get("quantity", 0))

    unmatched: list[dict[str, Any]] = []
    for res in resources:
        if res.get("resource_type", "").lower() != "microsoft.compute/virtualmachines":
            continue
        state = str(res.get("state", "")).lower()
        if "running" not in state and "powerstate/running" not in state:
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
    # On first run (no baseline yet) return empty to avoid mass notification
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
            continue
        last_pw = extra.get("last_password_change", "")
        if not last_pw:
            continue
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
    count = sum(
        1 for r in resources
        if r.get("resource_type", "").lower() == target_type
    )
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
            logger.warning("Skipping cost_threshold — cost data stale")
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


# ── Notification delivery ─────────────────────────────────────────────────────

def _render_email_html(
    rule: dict[str, Any], items: list[dict[str, Any]]
) -> str:
    trigger = rule["trigger_type"]
    label = TRIGGER_LABELS.get(trigger, trigger)
    name = rule["name"]
    custom_msg = rule.get("custom_message", "")

    def row(cells: list[str]) -> str:
        return "<tr>" + "".join(f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{c}</td>" for c in cells) + "</tr>"

    # Build table rows per domain
    if trigger in ("cost_threshold", "cost_spike", "advisor_savings"):
        headers = ["Detail", "Value"]
        if trigger == "cost_threshold" and items:
            rows_html = row(["Period / Threshold", f"{items[0].get('period','').title()} / ${items[0].get('threshold_usd', '')}"])
            rows_html += row(["Total cost", f"${items[0].get('total_cost', ''):.2f} {items[0].get('currency','')}"])
        elif trigger == "cost_spike" and items:
            rows_html = row(["Date", items[0].get("date", "")])
            rows_html += row(["Yesterday cost", f"${items[0].get('yesterday_cost', ''):.2f}"])
            rows_html += row(["Baseline avg", f"${items[0].get('baseline_avg', ''):.2f}"])
            rows_html += row(["Change", f"{items[0].get('pct_change', '')}%"])
        else:
            headers = ["Title", "Monthly savings", "Subscription"]
            rows_html = "".join(
                row([i.get("title",""), f"${i.get('monthly_savings',0):.2f}", i.get("subscription_name","")])
                for i in items[:20]
            )
    elif trigger in ("vm_deallocated", "vm_no_reservation"):
        headers = ["VM Name", "Size", "Location", "Resource Group", "Days Off"] if trigger == "vm_deallocated" else ["VM Name", "Size", "Location", "Resource Group"]
        rows_html = "".join(
            row([i.get("name",""), i.get("size",""), i.get("location",""), i.get("resource_group",""), str(i.get("days_deallocated",""))] if trigger == "vm_deallocated"
                else [i.get("name",""), i.get("size",""), i.get("location",""), i.get("resource_group","")])
            for i in items[:50]
        )
    elif trigger in ("new_guest_users", "accounts_disabled", "stale_accounts"):
        headers = ["Name", "UPN", "Department"]
        rows_html = "".join(
            row([i.get("display_name",""), i.get("principal_name",""), i.get("department","")])
            for i in items[:50]
        )
    else:
        headers = ["Name", "Type", "Resource Group"]
        rows_html = "".join(
            row([i.get("name",""), i.get("resource_type",""), i.get("resource_group","")])
            for i in items[:50]
        )

    header_cells = "".join(f"<th style='padding:6px 10px;text-align:left;color:#fff'>{h}</th>" for h in headers)
    overflow = f"<p style='color:#666;font-size:12px'>Showing 50 of {len(items)} items.</p>" if len(items) > 50 else ""
    custom_section = f"<p style='margin:12px 0'>{custom_msg.replace(chr(10),'<br>')}</p>" if custom_msg else ""

    return f"""
    <div style='font-family:sans-serif;max-width:700px'>
      <div style='background:#1e3a5f;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0'>
        <h2 style='margin:0;font-size:18px'>{label}</h2>
        <p style='margin:4px 0 0;font-size:13px;opacity:.85'>{name} · {len(items)} item{"s" if len(items) != 1 else ""}</p>
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


async def _deliver(
    rule: dict[str, Any], items: list[dict[str, Any]]
) -> tuple[str, str | None]:
    """Send email and/or Teams. Returns (status, error_str | None)."""
    from config import DATA_DIR  # noqa: F401 — just to confirm import works
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
    errors: list[str] = []
    successes = 0

    tasks: list[Any] = []
    if email_to:
        tasks.append(send_email(email_to, subject, html))
    if teams_url:
        card = _build_teams_card(rule, items, site_origin)
        tasks.append(_post_teams(teams_url, card))

    results = await asyncio.gather(*tasks, return_exceptions=True)
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


async def _post_teams(webhook_url: str, card: dict[str, Any]) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(webhook_url, json=card)
        if not resp.is_success:
            raise RuntimeError(f"Teams webhook returned {resp.status_code}: {resp.text[:200]}")
    return True


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
        return  # zero-match: no history row written

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
    loop = asyncio.get_running_loop()
    _bg_task = loop.create_task(_loop())


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
    from ai_client import _call_openai, _call_anthropic, get_available_models
    from config import OPENAI_API_KEY, ANTHROPIC_API_KEY  # type: ignore[attr-defined]

    models = get_available_models()
    if not models:
        return {"parsed": False, "error": "No AI models configured"}

    model = models[0]
    try:
        if model.provider == "openai":
            raw = _call_openai(model.id, _CHAT_SYSTEM_PROMPT, message)
        else:
            raw = _call_anthropic(model.id, _CHAT_SYSTEM_PROMPT, message)
        return json.loads(raw.strip())
    except (json.JSONDecodeError, Exception) as exc:
        return {"parsed": False, "error": str(exc)}
```

- [ ] Run tests: `cd backend && python -m pytest tests/test_azure_alert_engine.py -v`
  Expected: all PASS

- [ ] Commit: `git add backend/azure_alert_engine.py backend/tests/test_azure_alert_engine.py && git commit -m "feat: add Azure alert evaluators and delivery engine"`

---

## Task 4: Additional Engine Tests

- [ ] Add VM, identity, and resource evaluator tests to `test_azure_alert_engine.py`:

```python
def test_vm_deallocated_first_run_no_match(tmp_path, monkeypatch):
    """First observation inserts state row but does not match (not old enough)."""
    import azure_alert_store as store_mod
    store_mod.azure_alert_store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    from azure_alert_engine import evaluate_vm_deallocated
    vms = [{"id": "vm-1", "name": "vm1", "resource_type": "microsoft.compute/virtualmachines",
             "state": "PowerState/deallocated", "location": "eastus", "resource_group": "rg", "vm_size": ""}]
    result = evaluate_vm_deallocated(vms, {"min_days": 7})
    assert result == []  # first observation, not old enough

def test_vm_deallocated_matches_after_min_days(tmp_path, monkeypatch):
    import azure_alert_store as store_mod
    from datetime import datetime, timezone, timedelta
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    store_mod.azure_alert_store = store
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    store.set_vm_first_seen_deallocated("vm-1", old_ts)
    from azure_alert_engine import evaluate_vm_deallocated
    vms = [{"id": "vm-1", "name": "vm1", "resource_type": "microsoft.compute/virtualmachines",
             "state": "PowerState/deallocated", "location": "eastus", "resource_group": "rg", "vm_size": ""}]
    result = evaluate_vm_deallocated(vms, {"min_days": 7})
    assert len(result) == 1
    assert result[0]["days_deallocated"] >= 7

def test_vm_no_reservation_returns_uncovered(tmp_path):
    from azure_alert_engine import evaluate_vm_no_reservation
    vms = [
        {"id": "vm-1", "name": "vm1", "resource_type": "microsoft.compute/virtualmachines",
         "state": "PowerState/running", "vm_size": "Standard_D2s_v3", "location": "eastus", "resource_group": "rg"},
        {"id": "vm-2", "name": "vm2", "resource_type": "microsoft.compute/virtualmachines",
         "state": "PowerState/running", "vm_size": "Standard_D4s_v3", "location": "eastus", "resource_group": "rg"},
    ]
    reservations = [{"sku": "Standard_D2s_v3", "location": "eastus", "quantity": 1}]
    result = evaluate_vm_no_reservation(vms, reservations, {})
    assert len(result) == 1
    assert result[0]["name"] == "vm2"

def test_new_guest_users_baseline_returns_all(tmp_path):
    from azure_alert_engine import evaluate_new_guest_users
    users = [
        {"extra": {"user_type": "Guest", "created_datetime": "2026-01-01T00:00:00Z"}, "id": "u1"},
        {"extra": {"user_type": "Member", "created_datetime": "2026-01-01T00:00:00Z"}, "id": "u2"},
    ]
    result = evaluate_new_guest_users(users, last_run=None)
    assert len(result) == 1  # only the guest

def test_stale_accounts_excludes_on_prem(tmp_path):
    from azure_alert_engine import evaluate_stale_accounts
    from datetime import datetime, timezone, timedelta
    old_pw = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    users = [
        {"id": "u1", "enabled": True, "display_name": "Cloud User", "principal_name": "u1@x.com",
         "extra": {"on_prem_sync": "", "last_password_change": old_pw, "department": ""}},
        {"id": "u2", "enabled": True, "display_name": "OnPrem User", "principal_name": "u2@x.com",
         "extra": {"on_prem_sync": "true", "last_password_change": old_pw, "department": ""}},
    ]
    result = evaluate_stale_accounts(users, {"min_days": 90})
    assert len(result) == 1
    assert result[0]["display_name"] == "Cloud User"

def test_resource_untagged_finds_missing_tags(tmp_path):
    from azure_alert_engine import evaluate_resource_untagged
    resources = [
        {"id": "r1", "name": "res1", "resource_type": "t", "resource_group": "rg",
         "tags": {"env": "prod", "owner": "alice"}},
        {"id": "r2", "name": "res2", "resource_type": "t", "resource_group": "rg",
         "tags": {"env": "dev"}},  # missing "owner"
    ]
    result = evaluate_resource_untagged(resources, {"required_tags": ["env", "owner"]})
    assert len(result) == 1
    assert result[0]["name"] == "res2"
    assert "owner" in result[0]["missing_tags"]
```

- [ ] Run: `cd backend && python -m pytest tests/test_azure_alert_engine.py -v`
  Expected: all PASS

- [ ] Commit: `git add backend/tests/test_azure_alert_engine.py && git commit -m "test: add VM, identity, resource evaluator tests"`

---

## Task 5: Routes

**Files:**
- Create: `backend/routes_azure_alerts.py`
- Create: `backend/tests/test_routes_azure_alerts.py`

- [ ] Write failing route tests:

```python
# backend/tests/test_routes_azure_alerts.py
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

AZURE_HOST = {"host": "azure.movedocs.com"}

RULE_BODY = {
    "name": "Test rule",
    "domain": "cost",
    "trigger_type": "cost_threshold",
    "trigger_config": {"period": "monthly", "threshold_usd": 5000},
    "frequency": "daily",
    "recipients": "admin@example.com",
    "teams_webhook_url": "",
    "schedule_time": "09:00",
    "schedule_days": "0,1,2,3,4",
    "custom_subject": "",
    "custom_message": "",
}

def test_create_rule(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts, azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.post("/api/azure/alerts/rules", json=RULE_BODY, headers=AZURE_HOST)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test rule"
    assert data["id"]

def test_create_rule_requires_delivery_channel(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts, azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    body = {**RULE_BODY, "recipients": "", "teams_webhook_url": ""}
    resp = test_client.post("/api/azure/alerts/rules", json=body, headers=AZURE_HOST)
    assert resp.status_code == 422

def test_list_rules(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts, azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    store.create_rule({**RULE_BODY})
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.get("/api/azure/alerts/rules", headers=AZURE_HOST)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

def test_toggle_rule(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts, azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    rule = store.create_rule({**RULE_BODY})
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.post(f"/api/azure/alerts/rules/{rule['id']}/toggle", headers=AZURE_HOST)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

def test_delete_rule(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts, azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    rule = store.create_rule({**RULE_BODY})
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.delete(f"/api/azure/alerts/rules/{rule['id']}", headers=AZURE_HOST)
    assert resp.status_code == 204
    assert store.get_rule(rule["id"]) is None

def test_test_rule_dry_run(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts, azure_alert_store as store_mod, azure_alert_engine as engine
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    rule = store.create_rule({**RULE_BODY})
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    monkeypatch.setattr(engine, "_evaluate_rule", lambda r: [{"total_cost": 6000}])
    resp = test_client.post(f"/api/azure/alerts/rules/{rule['id']}/test", headers=AZURE_HOST)
    assert resp.status_code == 200
    assert resp.json()["match_count"] == 1

def test_trigger_types_catalog(test_client):
    resp = test_client.get("/api/azure/alerts/trigger-types", headers=AZURE_HOST)
    assert resp.status_code == 200
    data = resp.json()
    assert "cost" in data
    assert "cost_threshold" in data["cost"]

def test_not_available_on_helpdesk_host(test_client):
    resp = test_client.get("/api/azure/alerts/rules")
    assert resp.status_code == 404
```

- [ ] Run: `cd backend && python -m pytest tests/test_routes_azure_alerts.py -v`
  Expected: all FAIL with import or 404 errors

- [ ] Create `backend/routes_azure_alerts.py`:

```python
"""Azure alert rule CRUD and evaluation routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import require_admin, require_authenticated_user
from azure_alert_engine import TRIGGER_SCHEMA, _evaluate_rule, parse_azure_alert_rule
from azure_alert_store import azure_alert_store
from models import (
    AzureAlertHistoryItem,
    AzureAlertRuleCreate,
    AzureAlertRuleResponse,
    AzureAlertRuleUpdate,
    AzureAlertTestResponse,
    AzureChatParseRequest,
    AzureChatParseResponse,
)
from sitecontext import get_current_site_scope  # adjust import if needed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/azure/alerts")


def _ensure_azure_site() -> None:
    if get_current_site_scope() != "azure":
        raise HTTPException(status_code=404, detail="Azure portal APIs are only available on azure.movedocs.com")


def _get_rule_or_404(rule_id: str) -> dict[str, Any]:
    rule = azure_alert_store.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return rule


@router.get("/rules", response_model=list[AzureAlertRuleResponse])
def list_rules(_session: dict = Depends(require_authenticated_user)) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_alert_store.list_rules()


@router.post("/rules", response_model=AzureAlertRuleResponse, status_code=201)
def create_rule(
    body: AzureAlertRuleCreate,
    _session: dict = Depends(require_authenticated_user),
) -> dict[str, Any]:
    _ensure_azure_site()
    if not body.recipients.strip() and not body.teams_webhook_url.strip():
        raise HTTPException(status_code=422, detail="At least one delivery channel (recipients or teams_webhook_url) is required")
    return azure_alert_store.create_rule(body.model_dump())


@router.get("/rules/{rule_id}", response_model=AzureAlertRuleResponse)
def get_rule(rule_id: str, _session: dict = Depends(require_authenticated_user)) -> dict[str, Any]:
    _ensure_azure_site()
    return _get_rule_or_404(rule_id)


@router.put("/rules/{rule_id}", response_model=AzureAlertRuleResponse)
def update_rule(
    rule_id: str,
    body: AzureAlertRuleUpdate,
    _session: dict = Depends(require_authenticated_user),
) -> dict[str, Any]:
    _ensure_azure_site()
    _get_rule_or_404(rule_id)
    if not body.recipients.strip() and not body.teams_webhook_url.strip():
        raise HTTPException(status_code=422, detail="At least one delivery channel is required")
    updated = azure_alert_store.update_rule(rule_id, body.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return updated


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, _session: dict = Depends(require_authenticated_user)) -> None:
    _ensure_azure_site()
    _get_rule_or_404(rule_id)
    azure_alert_store.delete_rule(rule_id)


@router.post("/rules/{rule_id}/toggle", response_model=AzureAlertRuleResponse)
def toggle_rule(rule_id: str, _session: dict = Depends(require_authenticated_user)) -> dict[str, Any]:
    _ensure_azure_site()
    _get_rule_or_404(rule_id)
    result = azure_alert_store.toggle_rule(rule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return result


@router.post("/rules/{rule_id}/test", response_model=AzureAlertTestResponse)
def test_rule(rule_id: str, _session: dict = Depends(require_authenticated_user)) -> dict[str, Any]:
    _ensure_azure_site()
    rule = _get_rule_or_404(rule_id)
    try:
        items = _evaluate_rule(rule)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation error: {exc}") from exc
    return {"match_count": len(items), "sample_items": items[:10]}


@router.post("/rules/{rule_id}/send", status_code=202)
async def send_rule_now(rule_id: str, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    _ensure_azure_site()
    rule = _get_rule_or_404(rule_id)
    from azure_alert_engine import _deliver, _evaluate_rule
    items = _evaluate_rule(rule)
    if not items:
        return {"detail": "No matches — nothing sent"}
    status, error = await _deliver(rule, items)
    azure_alert_store.record_history(
        rule["id"], rule["name"], rule["trigger_type"],
        rule.get("recipients", ""), len(items), items, status, error,
    )
    azure_alert_store.update_last_run(rule["id"], last_sent=(status != "failed"))
    return {"status": status, "match_count": len(items), "error": error}


@router.post("/run", status_code=202)
def run_all_rules(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    _ensure_azure_site()
    from azure_alert_engine import run_due_rules
    import threading
    threading.Thread(target=run_due_rules, daemon=True).start()
    return {"detail": "Rule evaluation started in background"}


@router.get("/history", response_model=list[AzureAlertHistoryItem])
def get_history(
    limit: int = 100,
    rule_id: str | None = None,
    _session: dict = Depends(require_authenticated_user),
) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_alert_store.get_history(limit=limit, rule_id=rule_id)


@router.get("/trigger-types")
def get_trigger_types(_session: dict = Depends(require_authenticated_user)) -> dict[str, Any]:
    _ensure_azure_site()
    return TRIGGER_SCHEMA


@router.post("/chat-parse", response_model=AzureChatParseResponse)
def chat_parse(
    body: AzureChatParseRequest,
    _session: dict = Depends(require_authenticated_user),
) -> dict[str, Any]:
    _ensure_azure_site()
    result = parse_azure_alert_rule(body.message)
    if result.get("parsed"):
        rule_data = {k: v for k, v in result.items() if k not in ("parsed", "summary", "error")}
        return {
            "parsed": True,
            "rule": rule_data,
            "summary": result.get("summary", ""),
            "error": "",
        }
    return {"parsed": False, "rule": None, "summary": "", "error": result.get("error", "Could not parse")}
```

- [ ] Fix the `get_current_site_scope` import — check what module it lives in:
  ```bash
  cd backend && grep -r "def get_current_site_scope" --include="*.py" -l
  ```
  Update the import in `routes_azure_alerts.py` to match (likely `from sitecontext import ...` or `from config import ...`).

- [ ] Run: `cd backend && python -m pytest tests/test_routes_azure_alerts.py -v`
  Expected: all PASS

- [ ] Commit: `git add backend/routes_azure_alerts.py backend/tests/test_routes_azure_alerts.py && git commit -m "feat: add Azure alert CRUD and evaluation routes"`

---

## Task 6: Wire Backend

**Files:**
- Modify: `backend/main.py`

- [ ] Add import in `main.py` after existing Azure imports:

```python
from azure_alert_engine import start_azure_alert_loop, stop_azure_alert_loop
import routes_azure_alerts
```

- [ ] Register router in `main.py` (after `routes_azure` registration):

```python
app.include_router(routes_azure_alerts.router)
```

- [ ] Add loop to lifespan in `main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    kb_store.ensure_seed_articles()
    await cache.start_background_refresh()
    await azure_cache.start_background_refresh()
    await azure_vm_export_jobs.start_worker()
    await start_azure_alert_loop()   # ← add
    yield
    await stop_azure_alert_loop()    # ← add
    await azure_vm_export_jobs.stop_worker()
    await azure_cache.stop_background_refresh()
    await cache.stop_background_refresh()
```

- [ ] Smoke-test: `cd backend && python -c "import main; print('OK')`
  Expected: `OK`

- [ ] Run all backend tests: `cd backend && python -m pytest tests/ -v --tb=short`
  Expected: all PASS

- [ ] Commit: `git add backend/main.py && git commit -m "feat: wire Azure alert routes and background loop into main"`

---

## Task 7: Frontend API Types + Methods

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] Add TypeScript interfaces near the other Azure types in `api.ts`:

```typescript
export interface AzureAlertRule {
  id: string;
  name: string;
  domain: "cost" | "vms" | "identity" | "resources";
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  frequency: "immediate" | "hourly" | "daily" | "weekly";
  schedule_time: string;
  schedule_days: string;
  recipients: string;
  teams_webhook_url: string;
  custom_subject: string;
  custom_message: string;
  enabled: boolean;
  last_run: string | null;
  last_sent: string | null;
  created_at: string;
  updated_at: string;
}

export interface AzureAlertRuleCreate {
  name: string;
  domain: AzureAlertRule["domain"];
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  frequency: AzureAlertRule["frequency"];
  schedule_time: string;
  schedule_days: string;
  recipients: string;
  teams_webhook_url: string;
  custom_subject: string;
  custom_message: string;
}

export interface AzureAlertTestResponse {
  match_count: number;
  sample_items: Record<string, unknown>[];
}

export interface AzureAlertHistoryItem {
  id: string;
  rule_id: string;
  rule_name: string;
  trigger_type: string;
  sent_at: string;
  recipients: string;
  match_count: number;
  match_summary: Record<string, unknown>;
  status: "sent" | "partial" | "failed" | "dry_run";
  error: string | null;
}

export interface AzureChatParseResponse {
  parsed: boolean;
  rule: AzureAlertRuleCreate | null;
  summary: string;
  error: string;
}

export type AzureAlertTriggerSchema = Record<string, Record<string, Record<string, unknown>>>;
```

- [ ] Add API methods to the `api` object in `api.ts`:

```typescript
  getAzureAlertRules(): Promise<AzureAlertRule[]> {
    return fetchJSON<AzureAlertRule[]>("/api/azure/alerts/rules");
  },
  createAzureAlertRule(body: AzureAlertRuleCreate): Promise<AzureAlertRule> {
    return postJSON<AzureAlertRule>("/api/azure/alerts/rules", body);
  },
  updateAzureAlertRule(id: string, body: AzureAlertRuleCreate): Promise<AzureAlertRule> {
    return fetchJSON<AzureAlertRule>(`/api/azure/alerts/rules/${id}`, { method: "PUT", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
  },
  deleteAzureAlertRule(id: string): Promise<void> {
    return fetchJSON<void>(`/api/azure/alerts/rules/${id}`, { method: "DELETE" });
  },
  toggleAzureAlertRule(id: string): Promise<AzureAlertRule> {
    return postJSON<AzureAlertRule>(`/api/azure/alerts/rules/${id}/toggle`, {});
  },
  testAzureAlertRule(id: string): Promise<AzureAlertTestResponse> {
    return postJSON<AzureAlertTestResponse>(`/api/azure/alerts/rules/${id}/test`, {});
  },
  getAzureAlertHistory(params?: { limit?: number; rule_id?: string }): Promise<AzureAlertHistoryItem[]> {
    return fetchJSON<AzureAlertHistoryItem[]>(`/api/azure/alerts/history${buildQuery(params ?? {})}`);
  },
  getAzureAlertTriggerTypes(): Promise<AzureAlertTriggerSchema> {
    return fetchJSON<AzureAlertTriggerSchema>("/api/azure/alerts/trigger-types");
  },
  chatParseAzureAlert(message: string): Promise<AzureChatParseResponse> {
    return postJSON<AzureChatParseResponse>("/api/azure/alerts/chat-parse", { message });
  },
```

- [ ] Verify TypeScript: `cd frontend && npm run build 2>&1 | tail -5`
  Expected: build succeeds or only pre-existing errors

- [ ] Commit: `git add frontend/src/lib/api.ts && git commit -m "feat: add Azure alert API types and methods"`

---

## Task 8: AzureAlertsPage

**Files:**
- Create: `frontend/src/pages/AzureAlertsPage.tsx`

- [ ] Create the page. This is a large component — split into three logical sections within the same file:

```tsx
// frontend/src/pages/AzureAlertsPage.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type AzureAlertRule,
  type AzureAlertRuleCreate,
  type AzureAlertHistoryItem,
  type AzureChatParseResponse,
} from "../lib/api.ts";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";

// ── Helpers ───────────────────────────────────────────────────────────────────

const DOMAIN_COLORS: Record<string, string> = {
  cost: "bg-blue-100 text-blue-700",
  vms: "bg-purple-100 text-purple-700",
  identity: "bg-emerald-100 text-emerald-700",
  resources: "bg-amber-100 text-amber-700",
};

function DomainChip({ domain }: { domain: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${DOMAIN_COLORS[domain] ?? "bg-slate-100 text-slate-700"}`}>
      {domain}
    </span>
  );
}

function StatusChip({ status }: { status: string }) {
  const colors: Record<string, string> = {
    sent: "bg-emerald-100 text-emerald-700",
    partial: "bg-amber-100 text-amber-700",
    failed: "bg-red-100 text-red-700",
    dry_run: "bg-slate-100 text-slate-600",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${colors[status] ?? "bg-slate-100 text-slate-700"}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function formatSchedule(rule: AzureAlertRule): string {
  if (rule.frequency === "immediate") return "Every 10 min";
  if (rule.frequency === "hourly") return "Hourly";
  return `${rule.frequency.charAt(0).toUpperCase() + rule.frequency.slice(1)} ${rule.schedule_time} UTC`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

const EMPTY_RULE: AzureAlertRuleCreate = {
  name: "", domain: "cost", trigger_type: "", trigger_config: {},
  frequency: "daily", schedule_time: "09:00", schedule_days: "0,1,2,3,4",
  recipients: "", teams_webhook_url: "", custom_subject: "", custom_message: "",
};

// ── Quick Builder Modal ───────────────────────────────────────────────────────

function QuickBuilderModal({
  onClose,
  onEditInBuilder,
}: {
  onClose: () => void;
  onEditInBuilder: (rule: AzureAlertRuleCreate) => void;
}) {
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<AzureChatParseResponse | null>(null);
  const qc = useQueryClient();

  const parseMutation = useMutation({
    mutationFn: () => api.chatParseAzureAlert(message),
    onSuccess: (data) => setResult(data),
  });

  const saveMutation = useMutation({
    mutationFn: () => api.createAzureAlertRule(result!.rule!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["azure", "alerts", "rules"] });
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4" onClick={onClose}>
      <div
        className="w-full max-w-xl rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-slate-900">Quick Alert</h2>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">Close</button>
        </div>

        <p className="mt-3 text-sm text-slate-500">Describe what you want to monitor:</p>
        <ul className="mt-2 space-y-1 text-xs text-slate-400">
          <li>· "Alert me when monthly spend exceeds $10k"</li>
          <li>· "Email me when a VM is off for 7+ days"</li>
          <li>· "Notify Teams when new guests are added"</li>
        </ul>

        <div className="mt-4 flex gap-2">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !parseMutation.isPending && message.trim() && parseMutation.mutate()}
            placeholder="Describe your alert..."
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          <button
            type="button"
            onClick={() => parseMutation.mutate()}
            disabled={parseMutation.isPending || !message.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {parseMutation.isPending ? "..." : "Send"}
          </button>
        </div>

        {result && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            {result.parsed && result.rule ? (
              <>
                <div className="space-y-1 text-sm">
                  <div><span className="font-medium text-slate-500">Name:</span> {result.rule.name}</div>
                  <div><span className="font-medium text-slate-500">Domain:</span> {result.rule.domain}</div>
                  <div><span className="font-medium text-slate-500">Trigger:</span> {result.rule.trigger_type}</div>
                  <div><span className="font-medium text-slate-500">Schedule:</span> {result.rule.frequency} {result.rule.schedule_time} UTC</div>
                  {result.summary && <div className="mt-2 text-xs text-slate-400">{result.summary}</div>}
                </div>
                <div className="mt-4 flex gap-2">
                  <button type="button" onClick={() => { onEditInBuilder(result.rule!); onClose(); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100">Edit in Builder</button>
                  <button type="button" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
                    {saveMutation.isPending ? "Saving..." : "Save"}
                  </button>
                </div>
                {saveMutation.isError && <p className="mt-2 text-xs text-red-600">{(saveMutation.error as Error).message}</p>}
              </>
            ) : (
              <p className="text-sm text-red-700">I couldn't parse that — {result.error || "try the Builder instead."}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Form Builder Drawer ───────────────────────────────────────────────────────

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function FormBuilderDrawer({
  initial,
  editingId,
  onClose,
}: {
  initial: AzureAlertRuleCreate;
  editingId: string | null;
  onClose: () => void;
}) {
  const [form, setForm] = useState<AzureAlertRuleCreate>(initial);
  const [testResult, setTestResult] = useState<{ count: number } | null>(null);
  const [emailInput, setEmailInput] = useState("");
  const qc = useQueryClient();

  const triggerTypesQuery = useQuery({
    queryKey: ["azure", "alerts", "trigger-types"],
    queryFn: () => api.getAzureAlertTriggerTypes(),
    staleTime: 60_000,
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      editingId
        ? api.updateAzureAlertRule(editingId, form)
        : api.createAzureAlertRule(form),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["azure", "alerts", "rules"] });
      onClose();
    },
  });

  const testMutation = useMutation({
    mutationFn: async () => {
      // For test, we need an existing rule id. If creating, save first (silently) then test.
      if (editingId) return api.testAzureAlertRule(editingId);
      const created = await api.createAzureAlertRule(form);
      const result = await api.testAzureAlertRule(created.id);
      await api.deleteAzureAlertRule(created.id); // cleanup temp rule
      return result;
    },
    onSuccess: (data) => setTestResult({ count: data.match_count }),
  });

  const triggers = triggerTypesQuery.data ?? {};
  const domainTriggers = Object.keys(triggers[form.domain] ?? {});

  function setField<K extends keyof AzureAlertRuleCreate>(key: K, value: AzureAlertRuleCreate[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleDay(dayIdx: number) {
    const current = new Set(form.schedule_days.split(",").map(Number).filter((n) => !isNaN(n)));
    if (current.has(dayIdx)) current.delete(dayIdx); else current.add(dayIdx);
    setField("schedule_days", Array.from(current).sort().join(","));
  }

  const activeDays = new Set(form.schedule_days.split(",").map(Number).filter((n) => !isNaN(n)));
  const configSchema = (triggers[form.domain] ?? {})[form.trigger_type] ?? {};

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside className="flex h-full w-full max-w-lg flex-col overflow-hidden bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="border-b border-slate-200 px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{editingId ? "Edit Alert" : "New Alert"}</h2>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">Close</button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* Domain */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Domain</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {(["cost", "vms", "identity", "resources"] as const).map((d) => (
                <button key={d} type="button" onClick={() => { setField("domain", d); setField("trigger_type", ""); setField("trigger_config", {}); }}
                  className={`rounded-full border px-4 py-1.5 text-sm font-medium transition capitalize ${form.domain === d ? "border-sky-500 bg-sky-50 text-sky-700" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>
                  {d}
                </button>
              ))}
            </div>
          </section>

          {/* Trigger */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Trigger</h3>
            <select value={form.trigger_type} onChange={(e) => { setField("trigger_type", e.target.value); setField("trigger_config", {}); }}
              className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="">Select trigger...</option>
              {domainTriggers.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
            </select>
            {/* Dynamic config fields */}
            {Object.entries(configSchema).map(([key, defaultVal]) => (
              <div key={key} className="mt-3">
                <label className="text-xs font-medium text-slate-600 capitalize">{key.replace(/_/g, " ")}</label>
                {Array.isArray(defaultVal) ? (
                  <input value={(form.trigger_config[key] as string[] | undefined ?? []).join(", ")}
                    onChange={(e) => setField("trigger_config", { ...form.trigger_config, [key]: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                    placeholder="tag1, tag2, ..."
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                ) : typeof defaultVal === "number" ? (
                  <input type="number" value={(form.trigger_config[key] as number | undefined) ?? defaultVal}
                    onChange={(e) => setField("trigger_config", { ...form.trigger_config, [key]: Number(e.target.value) })}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                ) : typeof defaultVal === "string" && key === "period" ? (
                  <select value={(form.trigger_config[key] as string | undefined) ?? defaultVal}
                    onChange={(e) => setField("trigger_config", { ...form.trigger_config, [key]: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                    <option value="monthly">Monthly</option>
                    <option value="weekly">Weekly</option>
                  </select>
                ) : (
                  <input value={(form.trigger_config[key] as string | undefined) ?? String(defaultVal)}
                    onChange={(e) => setField("trigger_config", { ...form.trigger_config, [key]: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                )}
              </div>
            ))}
          </section>

          {/* Schedule */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Schedule</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {(["immediate", "hourly", "daily", "weekly"] as const).map((f) => (
                <button key={f} type="button" onClick={() => setField("frequency", f)}
                  className={`rounded-full border px-4 py-1.5 text-sm font-medium transition capitalize ${form.frequency === f ? "border-sky-500 bg-sky-50 text-sky-700" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>
                  {f}
                </button>
              ))}
            </div>
            {(form.frequency === "daily" || form.frequency === "weekly") && (
              <div className="mt-3 space-y-3">
                <div>
                  <label className="text-xs font-medium text-slate-600">Time (UTC)</label>
                  <input type="time" value={form.schedule_time} onChange={(e) => setField("schedule_time", e.target.value)}
                    className="mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="text-xs font-medium text-slate-600">Days</label>
                  <div className="mt-1 flex gap-1">
                    {WEEKDAYS.map((label, idx) => (
                      <button key={idx} type="button" onClick={() => toggleDay(idx)}
                        className={`rounded px-2 py-1 text-xs font-medium transition ${activeDays.has(idx) ? "bg-sky-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </section>

          {/* Notify */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Notify</h3>
            <div className="mt-2">
              <label className="text-xs font-medium text-slate-600">Email recipients</label>
              <div className="mt-1 flex flex-wrap gap-1">
                {form.recipients.split(",").filter((e) => e.trim()).map((email) => (
                  <span key={email} className="flex items-center gap-1 rounded-full bg-sky-50 px-2 py-0.5 text-xs text-sky-700">
                    {email.trim()}
                    <button type="button" onClick={() => setField("recipients", form.recipients.split(",").filter((e) => e.trim() !== email.trim()).join(","))} className="text-sky-400 hover:text-sky-700">×</button>
                  </span>
                ))}
              </div>
              <div className="mt-1 flex gap-2">
                <input value={emailInput} onChange={(e) => setEmailInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && emailInput.includes("@")) { setField("recipients", [form.recipients, emailInput.trim()].filter(Boolean).join(",")); setEmailInput(""); } }}
                  placeholder="email@company.com" className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                <button type="button" onClick={() => { if (emailInput.includes("@")) { setField("recipients", [form.recipients, emailInput.trim()].filter(Boolean).join(",")); setEmailInput(""); } }}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">Add</button>
              </div>
            </div>
            <div className="mt-3">
              <label className="text-xs font-medium text-slate-600">Teams webhook URL</label>
              <input value={form.teams_webhook_url} onChange={(e) => setField("teams_webhook_url", e.target.value)}
                placeholder="https://...webhook.office.com/..."
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
          </section>

          {/* Name + Save */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Name</h3>
            <input value={form.name} onChange={(e) => setField("name", e.target.value)}
              placeholder="My alert rule name"
              className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-sky-500" />
          </section>
        </div>

        <div className="border-t border-slate-200 px-6 py-4 flex items-center gap-3">
          <button type="button" onClick={() => testMutation.mutate()} disabled={testMutation.isPending || !form.trigger_type}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            {testMutation.isPending ? "Testing..." : "Test"}
          </button>
          {testResult !== null && (
            <span className="text-sm text-slate-600">{testResult.count} match{testResult.count !== 1 ? "es" : ""} now</span>
          )}
          <div className="flex-1" />
          {saveMutation.isError && (
            <span className="text-xs text-red-600">{(saveMutation.error as Error).message}</span>
          )}
          <button type="button" onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !form.name.trim() || !form.trigger_type || (!form.recipients.trim() && !form.teams_webhook_url.trim())}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
            {saveMutation.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </aside>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AzureAlertsPage() {
  const [tab, setTab] = useState<"rules" | "history">("rules");
  const [showQuick, setShowQuick] = useState(false);
  const [showBuilder, setShowBuilder] = useState(false);
  const [builderInitial, setBuilderInitial] = useState<AzureAlertRuleCreate>(EMPTY_RULE);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, number>>({});
  const qc = useQueryClient();

  const rulesQuery = useQuery({
    queryKey: ["azure", "alerts", "rules"],
    queryFn: () => api.getAzureAlertRules(),
    refetchInterval: 30_000,
  });

  const historyQuery = useQuery({
    queryKey: ["azure", "alerts", "history"],
    queryFn: () => api.getAzureAlertHistory({ limit: 200 }),
    enabled: tab === "history",
    refetchInterval: 60_000,
  });

  const toggleMutation = useMutation({
    mutationFn: (id: string) => api.toggleAzureAlertRule(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["azure", "alerts", "rules"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteAzureAlertRule(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["azure", "alerts", "rules"] }),
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => api.testAzureAlertRule(id),
    onSuccess: (data, id) => setTestResults((prev) => ({ ...prev, [id]: data.match_count })),
  });

  const rules = rulesQuery.data ?? [];
  const history = historyQuery.data ?? [];
  const rulesScroll = useInfiniteScrollCount(rules.length, 50, "rules");
  const historyScroll = useInfiniteScrollCount(history.length, 50, "history");
  const visibleRules = rules.slice(0, rulesScroll.visibleCount);
  const visibleHistory = history.slice(0, historyScroll.visibleCount);

  function openBuilder(initial: AzureAlertRuleCreate = EMPTY_RULE, id: string | null = null) {
    setBuilderInitial(initial);
    setEditingId(id);
    setShowBuilder(true);
  }

  function openEdit(rule: AzureAlertRule) {
    openBuilder({
      name: rule.name, domain: rule.domain, trigger_type: rule.trigger_type,
      trigger_config: rule.trigger_config as Record<string, unknown>,
      frequency: rule.frequency, schedule_time: rule.schedule_time,
      schedule_days: rule.schedule_days, recipients: rule.recipients,
      teams_webhook_url: rule.teams_webhook_url,
      custom_subject: rule.custom_subject, custom_message: rule.custom_message,
    }, rule.id);
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Alerts</h1>
          <p className="mt-1 text-sm text-slate-500">Monitor Azure and get notified when conditions are met.</p>
        </div>
        <div className="relative">
          <div className="flex overflow-hidden rounded-lg border border-slate-300 shadow-sm">
            <button type="button" onClick={() => setShowQuick(true)}
              className="border-r border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
              Quick (AI)
            </button>
            <button type="button" onClick={() => openBuilder()}
              className="bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
              Builder
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200">
        {(["rules", "history"] as const).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize transition border-b-2 -mb-px ${tab === t ? "border-sky-600 text-sky-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {t}
          </button>
        ))}
      </div>

      {/* Rules tab */}
      {tab === "rules" && (
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          {rulesQuery.isLoading ? (
            <div className="px-4 py-8 text-center text-sm text-slate-500">Loading alert rules...</div>
          ) : rules.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-slate-500">
              No alert rules yet — use Quick or Builder to create your first one.
            </div>
          ) : (
            <div className="overflow-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Domain</th>
                    <th className="px-4 py-3">Trigger</th>
                    <th className="px-4 py-3">Schedule</th>
                    <th className="px-4 py-3">Last Sent</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRules.map((rule, idx) => (
                    <tr key={rule.id} className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                      <td className="px-4 py-3">
                        <button type="button" onClick={() => openEdit(rule)} className="font-medium text-sky-700 hover:underline text-left">{rule.name}</button>
                      </td>
                      <td className="px-4 py-3"><DomainChip domain={rule.domain} /></td>
                      <td className="px-4 py-3 text-slate-600">{rule.trigger_type.replace(/_/g, " ")}</td>
                      <td className="px-4 py-3 text-slate-600 whitespace-nowrap">{formatSchedule(rule)}</td>
                      <td className="px-4 py-3 text-slate-500 whitespace-nowrap text-xs">{formatDate(rule.last_sent)}</td>
                      <td className="px-4 py-3">
                        <button type="button" onClick={() => toggleMutation.mutate(rule.id)}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${rule.enabled ? "bg-sky-600" : "bg-slate-300"}`}>
                          <span className={`inline-block h-3.5 w-3.5 translate-x-0.5 rounded-full bg-white shadow transition-transform ${rule.enabled ? "translate-x-4" : ""}`} />
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button type="button" onClick={() => testMutation.mutate(rule.id)} disabled={testMutation.isPending}
                            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50">
                            Test
                          </button>
                          {testResults[rule.id] !== undefined && (
                            <span className="text-xs text-slate-500">{testResults[rule.id]} hit{testResults[rule.id] !== 1 ? "s" : ""}</span>
                          )}
                          <button type="button" onClick={() => { if (confirm(`Delete "${rule.name}"?`)) deleteMutation.mutate(rule.id); }}
                            className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50">
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rulesScroll.hasMore && (
                <div ref={rulesScroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
                  Showing {visibleRules.length} of {rules.length} rules — scroll for more
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* History tab */}
      {tab === "history" && (
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          {historyQuery.isLoading ? (
            <div className="px-4 py-8 text-center text-sm text-slate-500">Loading alert history...</div>
          ) : history.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-slate-500">No alert history yet.</div>
          ) : (
            <div className="overflow-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Rule</th>
                    <th className="px-4 py-3">Trigger</th>
                    <th className="px-4 py-3">Sent At</th>
                    <th className="px-4 py-3">Recipients</th>
                    <th className="px-4 py-3">Matches</th>
                    <th className="px-4 py-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleHistory.map((item: AzureAlertHistoryItem, idx: number) => {
                    const emails = item.recipients.split(",").filter(Boolean);
                    const recipientLabel = emails.length > 1 ? `${emails[0]} +${emails.length - 1}` : emails[0] ?? "—";
                    return (
                      <tr key={item.id} className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                        <td className="px-4 py-3 font-medium text-slate-900">{item.rule_name}</td>
                        <td className="px-4 py-3 text-slate-600">{item.trigger_type.replace(/_/g, " ")}</td>
                        <td className="px-4 py-3 text-slate-500 whitespace-nowrap text-xs">{formatDate(item.sent_at)}</td>
                        <td className="px-4 py-3 text-slate-600 text-xs">{recipientLabel}</td>
                        <td className="px-4 py-3 font-semibold text-slate-900">{item.match_count}</td>
                        <td className="px-4 py-3"><StatusChip status={item.status} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {historyScroll.hasMore && (
                <div ref={historyScroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
                  Showing {visibleHistory.length} of {history.length} entries — scroll for more
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {showQuick && (
        <QuickBuilderModal
          onClose={() => setShowQuick(false)}
          onEditInBuilder={(rule) => openBuilder(rule)}
        />
      )}

      {showBuilder && (
        <FormBuilderDrawer
          initial={builderInitial}
          editingId={editingId}
          onClose={() => { setShowBuilder(false); setEditingId(null); }}
        />
      )}
    </div>
  );
}
```

- [ ] Commit: `git add frontend/src/pages/AzureAlertsPage.tsx && git commit -m "feat: add AzureAlertsPage with form builder, quick builder, and history tab"`

---

## Task 9: Wire Frontend

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] Add lazy import to `App.tsx` (with other Azure page imports):

```typescript
const AzureAlertsPage = lazy(() => import("./pages/AzureAlertsPage"));
```

- [ ] Add route to `App.tsx` inside the Azure branch, before the catch-all:

```typescript
<Route path="alerts" element={<AzureAlertsPage />} />
```

- [ ] Add nav item to `Layout.tsx` in `azureNavItems`, after the Copilot entry:

```typescript
{ to: "/alerts", label: "Alerts", icon: "\u25B2" },
```

- [ ] Verify TypeScript builds: `cd frontend && npm run build 2>&1 | tail -10`
  Expected: no new errors

- [ ] Commit: `git add frontend/src/App.tsx frontend/src/components/Layout.tsx && git commit -m "feat: wire Azure Alerts route and nav item"`

---

## Task 10: Fix `get_current_site_scope` Import

- [ ] Find the correct import in `routes_azure_alerts.py`:
  ```bash
  cd backend && grep -r "def get_current_site_scope" --include="*.py"
  ```

- [ ] Update the import line in `routes_azure_alerts.py` to match whatever module it's in. Common patterns seen in the codebase:
  ```python
  from sitecontext import get_current_site_scope
  # OR
  from config import get_current_site_scope
  # OR
  from auth import get_current_site_scope
  ```

- [ ] Re-run all backend tests: `cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -20`
  Expected: all PASS

- [ ] Run full test suite: `cd backend && python -m pytest tests/ && cd ../frontend && npm run test:run`
  Expected: all PASS

- [ ] Final commit: `git add -p && git commit -m "fix: correct site scope import in azure alert routes"`

---

## Verification Checklist

- [ ] `GET /api/azure/alerts/rules` returns `[]` on clean start (Azure host)
- [ ] `GET /api/azure/alerts/rules` returns 404 on helpdesk host
- [ ] Creating a rule with no recipients or webhook returns 422
- [ ] Toggle disables/enables correctly
- [ ] `/alerts` route renders in browser without console errors
- [ ] Form builder opens as a drawer, Quick builder as a modal
- [ ] Quick builder "Edit in Builder" pre-fills the form
- [ ] History tab loads after navigating to it
- [ ] TypeScript: `npm run build` passes with no errors
