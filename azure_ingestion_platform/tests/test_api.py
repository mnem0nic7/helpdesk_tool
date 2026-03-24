from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def test_onboarding_flow_and_source_listing(platform_app):
    client = platform_app["client"]

    sources = client.get("/api/v1/collector-sources")
    assert sources.status_code == 200
    payload = sources.json()
    assert any(item["source"] == "resource_graph" and item["implemented"] for item in payload)
    assert any(item["source"] == "activity_log" and item["implemented"] for item in payload)
    assert any(item["source"] == "advisor" and not item["implemented"] for item in payload)

    start = client.post(
        "/api/v1/tenants/onboarding",
        json={
            "slug": "contoso",
            "display_name": "Contoso",
            "tenant_external_id": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert start.status_code == 200
    onboarding = start.json()
    assert onboarding["tenant"]["status"] == "pending_consent"
    parsed = urlparse(onboarding["consent_url"])
    state = parse_qs(parsed.query)["state"][0]

    callback = client.get(
        "/api/v1/onboarding/callback",
        params={"tenant": "11111111-1111-1111-1111-111111111111", "state": state, "admin_consent": "True"},
    )
    assert callback.status_code == 200
    assert callback.json()["status"] == "active"


def test_enqueue_run_for_active_tenant(platform_app):
    client = platform_app["client"]
    create = client.post(
        "/api/v1/tenants/onboarding",
        json={
            "slug": "fabrikam",
            "display_name": "Fabrikam",
            "tenant_external_id": "22222222-2222-2222-2222-222222222222",
        },
    ).json()
    state = parse_qs(urlparse(create["consent_url"]).query)["state"][0]
    client.get(
        "/api/v1/onboarding/callback",
        params={"tenant": "22222222-2222-2222-2222-222222222222", "state": state, "admin_consent": "true"},
    )

    run_resp = client.post(
        f"/api/v1/tenants/{create['tenant']['id']}/runs",
        json={"source": "resource_graph", "subscription_ids": []},
    )
    assert run_resp.status_code == 200
    assert run_resp.json()["status"] == "pending"

    runs = client.get("/api/v1/ingestion-runs", params={"tenant_id": create["tenant"]["id"]})
    assert runs.status_code == 200
    assert len(runs.json()) == 1
