from __future__ import annotations

from types import SimpleNamespace

import pytest

from alert_store import AlertStore


def _issue(
    key: str,
    request_type: str,
    *,
    summary: str | None = None,
    priority: str = "Medium",
    assignee: str | None = "Alice Admin",
    status: str = "Open",
) -> dict:
    assignee_obj = {"displayName": assignee} if assignee else None
    return {
        "key": key,
        "fields": {
            "summary": summary or f"{request_type} ticket",
            "priority": {"name": priority},
            "assignee": assignee_obj,
            "status": {"name": status, "statusCategory": {"name": "To Do"}},
            "customfield_10010": {"requestType": {"name": request_type}},
            "created": "2026-03-09T00:00:00+00:00",
            "updated": "2026-03-09T00:00:00+00:00",
        },
    }


@pytest.mark.asyncio
async def test_run_alert_checks_only_sends_unseen_new_ticket_matches(tmp_path, monkeypatch):
    import alert_engine

    store = AlertStore(str(tmp_path / "alerts.db"))
    monkeypatch.setattr(alert_engine, "alert_store", store)
    monkeypatch.setattr(alert_engine, "_refresh_tickets", lambda tickets: tickets)

    sends: list[dict[str, object]] = []

    async def fake_send_email(to, subject, html, cc=None):
        sends.append({"to": to, "subject": subject, "html": html, "cc": cc})
        return True

    monkeypatch.setattr(alert_engine, "send_email", fake_send_email)

    rule = store.create_rule({
        "name": "Security arrivals",
        "trigger_type": "new_ticket",
        "frequency": "immediate",
        "recipients": "security@example.com",
        "filters": {"request_types": ["Security Alert"]},
    })

    first_issue = _issue("OIT-1", "Security Alert", priority="High")
    non_match = _issue("OIT-2", "Get IT help")

    sent_count = await alert_engine.run_alert_checks([first_issue, non_match])

    assert sent_count == 1
    assert len(sends) == 1
    assert "OIT-1" in str(sends[0]["html"])
    assert store.get_seen_ticket_keys(rule["id"]) == {"OIT-1"}

    sent_count = await alert_engine.run_alert_checks([first_issue, non_match])

    assert sent_count == 0
    assert len(sends) == 1

    second_issue = _issue("OIT-3", "Security Alert", priority="Highest")
    sent_count = await alert_engine.run_alert_checks([first_issue, second_issue, non_match])

    assert sent_count == 1
    assert len(sends) == 2
    assert "OIT-3" in str(sends[1]["html"])
    assert store.get_seen_ticket_keys(rule["id"]) == {"OIT-1", "OIT-3"}


@pytest.mark.asyncio
async def test_create_new_ticket_rule_baselines_existing_matching_tickets(tmp_path, monkeypatch):
    import alert_engine
    import routes_alerts

    store = AlertStore(str(tmp_path / "alerts.db"))
    issues = [
        _issue("OIT-10", "Security Alert"),
        _issue("OIT-11", "Get IT help"),
    ]
    mock_cache = SimpleNamespace(get_filtered_issues=lambda: list(issues))

    monkeypatch.setattr(alert_engine, "alert_store", store)
    monkeypatch.setattr(routes_alerts, "alert_store", store)
    monkeypatch.setattr(routes_alerts, "cache", mock_cache)

    rule = await routes_alerts.create_rule({
        "name": "Security arrivals",
        "trigger_type": "new_ticket",
        "frequency": "immediate",
        "recipients": "security@example.com",
        "filters": {"request_types": ["Security Alert"]},
    })

    assert store.get_seen_ticket_keys(rule["id"]) == {"OIT-10"}

    initial_preview = await routes_alerts.test_rule(rule["id"])
    assert initial_preview["matching_count"] == 0
    assert initial_preview["sample_keys"] == []

    issues.append(_issue("OIT-12", "Security Alert"))

    updated_preview = await routes_alerts.test_rule(rule["id"])
    assert updated_preview["matching_count"] == 1
    assert updated_preview["sample_keys"] == ["OIT-12"]


def test_alert_store_scopes_rules_and_history(tmp_path):
    store = AlertStore(str(tmp_path / "alerts.db"))

    primary_rule = store.create_rule({
        "name": "Primary rule",
        "trigger_type": "stale",
        "recipients": "primary@example.com",
    })
    oasis_rule = store.create_rule({
        "name": "Oasis rule",
        "trigger_type": "stale",
        "recipients": "oasis@example.com",
        "site_scope": "oasisdev",
    })

    store.record_send(primary_rule, ["OIT-1"])
    store.record_send(oasis_rule, ["OIT-500"])

    assert [rule["name"] for rule in store.get_rules(site_scope="primary")] == ["Primary rule"]
    assert [rule["name"] for rule in store.get_rules(site_scope="oasisdev")] == ["Oasis rule"]
    assert store.get_history(site_scope="primary")[0]["ticket_keys"] == ["OIT-1"]
    assert store.get_history(site_scope="oasisdev")[0]["ticket_keys"] == ["OIT-500"]


@pytest.mark.parametrize(
    ("site_scope", "expected_host"),
    [
        ("primary", "https://it-app.movedocs.com"),
        ("oasisdev", "https://oasisdev.movedocs.com"),
    ],
)
def test_render_email_links_back_to_local_ticket_view(site_scope, expected_host):
    import alert_engine

    rule = {
        "name": "Security arrivals",
        "trigger_type": "new_ticket",
    }
    subject, html = alert_engine._render_email(
        rule,
        [_issue("OIT-42", "Security Alert", priority="High")],
        site_scope=site_scope,
    )

    assert subject.startswith("[")
    assert f'href="{expected_host}/tickets?ticket=OIT-42"' in html
    assert f'href="{expected_host}/alerts"' in html
    assert "browse/OIT-42" not in html
