from __future__ import annotations

from unittest.mock import MagicMock

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
    import routes_azure_alerts
    import azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.post("/api/azure/alerts/rules", json=RULE_BODY, headers=AZURE_HOST)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test rule"
    assert data["id"]


def test_create_rule_requires_delivery_channel(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts
    import azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    body = {**RULE_BODY, "recipients": "", "teams_webhook_url": ""}
    resp = test_client.post("/api/azure/alerts/rules", json=body, headers=AZURE_HOST)
    assert resp.status_code == 422


def test_list_rules(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts
    import azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    store.create_rule(RULE_BODY)
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.get("/api/azure/alerts/rules", headers=AZURE_HOST)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_toggle_rule(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts
    import azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    rule = store.create_rule(RULE_BODY)
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.post(f"/api/azure/alerts/rules/{rule['id']}/toggle", headers=AZURE_HOST)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_delete_rule(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts
    import azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    rule = store.create_rule(RULE_BODY)
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.delete(f"/api/azure/alerts/rules/{rule['id']}", headers=AZURE_HOST)
    assert resp.status_code == 204
    assert store.get_rule(rule["id"]) is None


def test_test_rule_dry_run(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts
    import azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    rule = store.create_rule(RULE_BODY)
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    # Patch the binding in the routes module (it imported _evaluate_rule directly)
    monkeypatch.setattr(routes_azure_alerts, "_evaluate_rule", lambda r: [{"total_cost": 6000}])
    resp = test_client.post(f"/api/azure/alerts/rules/{rule['id']}/test", headers=AZURE_HOST)
    assert resp.status_code == 200
    assert resp.json()["match_count"] == 1


def test_trigger_types_catalog(test_client):
    resp = test_client.get("/api/azure/alerts/trigger-types", headers=AZURE_HOST)
    assert resp.status_code == 200
    data = resp.json()
    assert "cost" in data
    assert "cost_threshold" in data["cost"]


def test_history_empty(test_client, monkeypatch, tmp_path):
    import routes_azure_alerts
    import azure_alert_store as store_mod
    store = store_mod.AzureAlertStore(str(tmp_path / "a.db"))
    monkeypatch.setattr(routes_azure_alerts, "azure_alert_store", store)
    resp = test_client.get("/api/azure/alerts/history", headers=AZURE_HOST)
    assert resp.status_code == 200
    assert resp.json() == []


def test_not_available_on_helpdesk_host(test_client):
    resp = test_client.get("/api/azure/alerts/rules")
    assert resp.status_code == 404
