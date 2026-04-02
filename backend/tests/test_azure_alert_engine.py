from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest


# ── Cost evaluators ───────────────────────────────────────────────────────────

def _make_trend(days: int, base_cost: float = 100.0) -> list[dict]:
    today = datetime.now(timezone.utc)
    return [
        {
            "date": (today - timedelta(days=days - i)).strftime("%Y-%m-%d"),
            "cost": base_cost,
            "currency": "USD",
        }
        for i in range(days)
    ]


def test_cost_threshold_monthly_matches():
    from azure_alert_engine import evaluate_cost_threshold
    trend = _make_trend(30, base_cost=400.0)  # 30 * 400 = 12000
    result = evaluate_cost_threshold(trend, {"period": "monthly", "threshold_usd": 10000})
    assert len(result) == 1
    assert result[0]["total_cost"] == pytest.approx(12000.0)


def test_cost_threshold_monthly_no_match():
    from azure_alert_engine import evaluate_cost_threshold
    trend = _make_trend(30, base_cost=10.0)  # 300 total
    result = evaluate_cost_threshold(trend, {"period": "monthly", "threshold_usd": 10000})
    assert result == []


def test_cost_threshold_weekly_uses_last_7():
    from azure_alert_engine import evaluate_cost_threshold
    trend = _make_trend(30, base_cost=10.0)  # last 7 = 70, threshold = 60
    result = evaluate_cost_threshold(trend, {"period": "weekly", "threshold_usd": 60})
    assert len(result) == 1


def test_cost_spike_detects_spike():
    from azure_alert_engine import evaluate_cost_spike
    today = datetime.now(timezone.utc)
    # 6 baseline rows at 100, yesterday at 200, today partial at 50 (excluded)
    trend = [
        {"date": (today - timedelta(days=8 - i)).strftime("%Y-%m-%d"), "cost": 100.0, "currency": "USD"}
        for i in range(6)
    ]
    trend.append({"date": (today - timedelta(days=1)).strftime("%Y-%m-%d"), "cost": 200.0, "currency": "USD"})
    trend.append({"date": today.strftime("%Y-%m-%d"), "cost": 50.0, "currency": "USD"})
    result = evaluate_cost_spike(trend, {"spike_pct": 20})
    assert len(result) == 1
    assert result[0]["pct_change"] == pytest.approx(100.0)


def test_cost_spike_no_spike():
    from azure_alert_engine import evaluate_cost_spike
    trend = _make_trend(10, base_cost=100.0)
    result = evaluate_cost_spike(trend, {"spike_pct": 20})
    assert result == []


def test_cost_spike_insufficient_data():
    from azure_alert_engine import evaluate_cost_spike
    trend = _make_trend(2, base_cost=999.0)
    result = evaluate_cost_spike(trend, {"spike_pct": 20})
    assert result == []


def test_advisor_savings_filters_threshold():
    from azure_alert_engine import evaluate_advisor_savings
    items = [
        {"title": "Big saving", "monthly_savings": 500.0, "annual_savings": 6000.0,
         "currency": "USD", "description": "", "subscription_name": "Prod"},
        {"title": "Tiny saving", "monthly_savings": 10.0, "annual_savings": 120.0,
         "currency": "USD", "description": "", "subscription_name": "Dev"},
    ]
    result = evaluate_advisor_savings(items, {"min_monthly_savings_usd": 100.0})
    assert len(result) == 1
    assert result[0]["title"] == "Big saving"


# ── VM evaluators ─────────────────────────────────────────────────────────────

def test_vm_deallocated_first_run_no_match(tmp_path, monkeypatch):
    import azure_alert_store as store_mod
    import azure_alert_engine as engine
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(store_mod, "azure_alert_store", store)
    monkeypatch.setattr(engine, "azure_alert_store", store)
    from azure_alert_engine import evaluate_vm_deallocated
    vms = [{"id": "vm-1", "name": "vm1", "resource_type": "microsoft.compute/virtualmachines",
             "state": "PowerState/deallocated", "location": "eastus", "resource_group": "rg", "vm_size": ""}]
    result = evaluate_vm_deallocated(vms, {"min_days": 7})
    assert result == []  # first observation — not old enough yet


def test_vm_deallocated_matches_after_min_days(tmp_path, monkeypatch):
    import azure_alert_store as store_mod
    import azure_alert_engine as engine
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(store_mod, "azure_alert_store", store)
    monkeypatch.setattr(engine, "azure_alert_store", store)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    store.set_vm_first_seen_deallocated("vm-1", old_ts)
    from azure_alert_engine import evaluate_vm_deallocated
    vms = [{"id": "vm-1", "name": "vm1", "resource_type": "microsoft.compute/virtualmachines",
             "state": "PowerState/deallocated", "location": "eastus", "resource_group": "rg", "vm_size": ""}]
    result = evaluate_vm_deallocated(vms, {"min_days": 7})
    assert len(result) == 1
    assert result[0]["days_deallocated"] >= 7


def test_vm_no_reservation_returns_uncovered():
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


def test_vm_no_reservation_covered():
    from azure_alert_engine import evaluate_vm_no_reservation
    vms = [
        {"id": "vm-1", "name": "vm1", "resource_type": "microsoft.compute/virtualmachines",
         "state": "PowerState/running", "vm_size": "Standard_D2s_v3", "location": "eastus", "resource_group": "rg"},
    ]
    reservations = [{"sku": "Standard_D2s_v3", "location": "eastus", "quantity": 2}]
    result = evaluate_vm_no_reservation(vms, reservations, {})
    assert result == []


# ── Identity evaluators ───────────────────────────────────────────────────────

def test_new_guest_users_baseline_returns_all_guests():
    from azure_alert_engine import evaluate_new_guest_users
    users = [
        {"id": "u1", "extra": {"user_type": "Guest", "created_datetime": "2026-01-01T00:00:00Z"}},
        {"id": "u2", "extra": {"user_type": "Member", "created_datetime": "2026-01-01T00:00:00Z"}},
    ]
    result = evaluate_new_guest_users(users, last_run=None)
    assert len(result) == 1
    assert result[0]["id"] == "u1"


def test_new_guest_users_after_last_run():
    from azure_alert_engine import evaluate_new_guest_users
    users = [
        {"id": "u1", "extra": {"user_type": "Guest", "created_datetime": "2026-03-10T00:00:00Z"}},
        {"id": "u2", "extra": {"user_type": "Guest", "created_datetime": "2026-01-01T00:00:00Z"}},
    ]
    result = evaluate_new_guest_users(users, last_run="2026-03-01T00:00:00Z")
    assert len(result) == 1
    assert result[0]["id"] == "u1"


def test_accounts_disabled_first_run_no_match(tmp_path, monkeypatch):
    import azure_alert_store as store_mod
    import azure_alert_engine as engine
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(store_mod, "azure_alert_store", store)
    monkeypatch.setattr(engine, "azure_alert_store", store)
    from azure_alert_engine import evaluate_accounts_disabled
    users = [{"id": "u1", "enabled": False, "display_name": "A", "principal_name": "a@x.com",
               "extra": {"department": ""}}]
    result = evaluate_accounts_disabled(users)
    assert result == []  # no baseline yet


def test_accounts_disabled_detects_change(tmp_path, monkeypatch):
    import azure_alert_store as store_mod
    import azure_alert_engine as engine
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(store_mod, "azure_alert_store", store)
    monkeypatch.setattr(engine, "azure_alert_store", store)
    # Baseline: u1 was enabled
    store.upsert_user_state("u1", True)
    from azure_alert_engine import evaluate_accounts_disabled
    users = [{"id": "u1", "enabled": False, "display_name": "A", "principal_name": "a@x.com",
               "extra": {"department": ""}}]
    result = evaluate_accounts_disabled(users)
    assert len(result) == 1
    assert result[0]["id"] == "u1"


def test_stale_accounts_excludes_on_prem():
    from azure_alert_engine import evaluate_stale_accounts
    old_pw = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    users = [
        {"id": "u1", "enabled": True, "display_name": "Cloud", "principal_name": "c@x.com",
         "extra": {"on_prem_sync": "", "last_password_change": old_pw, "department": ""}},
        {"id": "u2", "enabled": True, "display_name": "OnPrem", "principal_name": "o@x.com",
         "extra": {"on_prem_sync": "true", "last_password_change": old_pw, "department": ""}},
    ]
    result = evaluate_stale_accounts(users, {"min_days": 90})
    assert len(result) == 1
    assert result[0]["display_name"] == "Cloud"


def test_stale_accounts_skips_empty_password():
    from azure_alert_engine import evaluate_stale_accounts
    users = [{"id": "u1", "enabled": True, "display_name": "A", "principal_name": "a@x.com",
               "extra": {"on_prem_sync": "", "last_password_change": "", "department": ""}}]
    result = evaluate_stale_accounts(users, {"min_days": 90})
    assert result == []


# ── Resource evaluators ───────────────────────────────────────────────────────

def test_resource_count_exceeded():
    from azure_alert_engine import evaluate_resource_count_exceeded
    resources = [
        {"id": f"r{i}", "resource_type": "microsoft.compute/virtualmachines"}
        for i in range(5)
    ]
    assert evaluate_resource_count_exceeded(resources, {"resource_type": "microsoft.compute/virtualmachines", "threshold": 3}) != []
    assert evaluate_resource_count_exceeded(resources, {"resource_type": "microsoft.compute/virtualmachines", "threshold": 10}) == []


def test_resource_untagged_finds_missing():
    from azure_alert_engine import evaluate_resource_untagged
    resources = [
        {"id": "r1", "name": "res1", "resource_type": "t", "resource_group": "rg",
         "tags": {"env": "prod", "owner": "alice"}},
        {"id": "r2", "name": "res2", "resource_type": "t", "resource_group": "rg",
         "tags": {"env": "dev"}},  # missing "owner"
        {"id": "r3", "name": "res3", "resource_type": "t", "resource_group": "rg",
         "tags": {}},
    ]
    result = evaluate_resource_untagged(resources, {"required_tags": ["env", "owner"]})
    assert len(result) == 2
    names = {r["name"] for r in result}
    assert names == {"res2", "res3"}


def test_resource_untagged_empty_required_tags():
    from azure_alert_engine import evaluate_resource_untagged
    resources = [{"id": "r1", "name": "r1", "resource_type": "t", "resource_group": "rg", "tags": {}}]
    assert evaluate_resource_untagged(resources, {"required_tags": []}) == []


def test_parse_azure_alert_rule_uses_shared_ai_invocation(monkeypatch):
    import ai_client
    import azure_alert_engine as engine
    import config

    class _FastModel:
        id = "nemotron-3-nano:4b"
        provider = "ollama"

    class _QualityModel:
        id = "qwen3.5:4b"
        provider = "ollama"

    captured: dict[str, object] = {}

    monkeypatch.setattr(ai_client, "get_available_models", lambda: [_FastModel(), _QualityModel()])
    monkeypatch.setattr(config, "AZURE_ALERT_RULE_MODEL", "nemotron-3-nano:4b")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen3.5:4b")
    monkeypatch.setattr(
        ai_client,
        "invoke_model_text",
        lambda model_id, system, user_msg, **kwargs: captured.update({"model_id": model_id, **kwargs}) or '{"parsed": true, "name": "Monthly cost", "domain": "cost", "trigger_type": "cost_threshold", "trigger_config": {"period": "monthly", "threshold_usd": 1000}, "frequency": "daily", "schedule_time": "09:00", "schedule_days": "0,1,2,3,4", "recipients": "", "teams_webhook_url": "", "summary": "Daily threshold"}',
    )

    result = engine.parse_azure_alert_rule("alert me when cost crosses 1000 this month")

    assert result["parsed"] is True
    assert result["trigger_type"] == "cost_threshold"
    assert captured["model_id"] == "nemotron-3-nano:4b"
    assert captured["max_output_tokens"] == 220
    assert captured["json_output"] is True


def test_build_recommendation_teams_card_includes_recommendation_details():
    from azure_alert_engine import build_recommendation_teams_card

    card = build_recommendation_teams_card(
        {
            "id": "rec-1",
            "title": "Release unattached public IP pip-1",
            "summary": "The public IP is not attached.",
            "category": "network",
            "opportunity_type": "unattached_public_ip",
            "resource_name": "pip-1",
            "subscription_name": "Prod",
            "currency": "USD",
            "estimated_monthly_savings": 5.0,
            "portal_url": "https://portal.azure.com/#resource/pip-1",
            "follow_up_route": "/resources",
        },
        site_origin="https://azure.movedocs.com",
        channel_label="FinOps Watch",
        operator_note="Please review this in standup.",
    )

    content = card["attachments"][0]["content"]
    body = content["body"]
    assert body[0]["text"] == "Azure FinOps Recommendation · FinOps Watch"
    assert "Release unattached public IP pip-1" in body[1]["text"]
    assert "Please review this in standup." in body[-1]["text"]
    assert content["actions"][0]["url"] == "https://azure.movedocs.com/savings"


@pytest.mark.asyncio
async def test_send_recommendation_teams_alert_posts_card(monkeypatch):
    import azure_alert_engine as engine

    calls: list[tuple[str, dict]] = []

    async def _fake_post(webhook_url: str, card: dict[str, object]) -> bool:
        calls.append((webhook_url, card))
        return True

    monkeypatch.setattr(engine, "_post_teams", _fake_post)

    result = await engine.send_recommendation_teams_alert(
        "https://hooks.example.test/finops",
        {"id": "rec-1", "title": "Right-size VM vm-1", "category": "compute", "follow_up_route": "/compute"},
        site_origin="https://azure.movedocs.com",
        channel_label="FinOps",
        operator_note="Please follow up.",
    )

    assert result is True
    assert calls[0][0] == "https://hooks.example.test/finops"
    assert calls[0][1]["attachments"][0]["content"]["actions"][2]["url"] == "https://azure.movedocs.com/compute"
