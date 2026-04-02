from __future__ import annotations

from models import (
    AIModel,
    SecurityCopilotAnswer,
    SecurityCopilotChatResponse,
    SecurityCopilotIncident,
)


def _response(*, phase: str, assistant_message: str) -> SecurityCopilotChatResponse:
    return SecurityCopilotChatResponse(
        phase=phase,  # type: ignore[arg-type]
        assistant_message=assistant_message,
        incident=SecurityCopilotIncident(
            lane="identity_compromise",
            summary="Suspicious sign-in activity",
            timeframe="Since 2 AM UTC",
            affected_users=["ada@example.com"],
        ),
        follow_up_questions=[],
        planned_sources=[],
        source_results=[],
        jobs=[],
        answer=SecurityCopilotAnswer(summary="Completed") if phase == "complete" else SecurityCopilotAnswer(),
        citations=[],
        model_used="qwen2.5:7b",
        generated_at="2026-04-02T02:00:00+00:00",
    )


def test_security_copilot_route_requires_message_or_context(test_client, monkeypatch):
    import routes_azure_security_copilot

    monkeypatch.setattr(
        routes_azure_security_copilot,
        "get_available_copilot_models",
        lambda: [AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama")],
    )
    monkeypatch.setattr(routes_azure_security_copilot, "get_default_copilot_model_id", lambda models: models[0].id)

    resp = test_client.post(
        "/api/azure/security/copilot/chat",
        headers={"host": "azure.movedocs.com"},
        json={"message": "", "incident": {"lane": "unknown"}},
    )

    assert resp.status_code == 400
    assert "Message or existing incident context is required" in resp.json()["detail"]


def test_security_copilot_route_rejects_unavailable_model(test_client, monkeypatch):
    import routes_azure_security_copilot

    monkeypatch.setattr(
        routes_azure_security_copilot,
        "get_available_copilot_models",
        lambda: [AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama")],
    )
    monkeypatch.setattr(routes_azure_security_copilot, "get_default_copilot_model_id", lambda models: models[0].id)

    resp = test_client.post(
        "/api/azure/security/copilot/chat",
        headers={"host": "azure.movedocs.com"},
        json={"message": "Investigate ada@example.com", "model": "qwen2.5:3b"},
    )

    assert resp.status_code == 400
    assert "is not available from the active Ollama provider" in resp.json()["detail"]


def test_security_copilot_route_returns_needs_input_response(test_client, monkeypatch):
    import routes_azure_security_copilot

    monkeypatch.setattr(
        routes_azure_security_copilot,
        "get_available_copilot_models",
        lambda: [AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama")],
    )
    monkeypatch.setattr(routes_azure_security_copilot, "get_default_copilot_model_id", lambda models: models[0].id)
    monkeypatch.setattr(
        routes_azure_security_copilot,
        "run_security_copilot_chat",
        lambda body, session, model_id: _response(
            phase="needs_input",
            assistant_message="I still need the timeframe and affected mailbox.",
        ),
    )

    resp = test_client.post(
        "/api/azure/security/copilot/chat",
        headers={"host": "azure.movedocs.com"},
        json={"message": "Mailbox is acting strange"},
    )

    assert resp.status_code == 200
    assert resp.json()["phase"] == "needs_input"
    assert "timeframe" in resp.json()["assistant_message"]


def test_security_copilot_route_returns_running_jobs_response(test_client, monkeypatch):
    import routes_azure_security_copilot

    monkeypatch.setattr(
        routes_azure_security_copilot,
        "get_available_copilot_models",
        lambda: [AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama")],
    )
    monkeypatch.setattr(routes_azure_security_copilot, "get_default_copilot_model_id", lambda models: models[0].id)
    monkeypatch.setattr(
        routes_azure_security_copilot,
        "run_security_copilot_chat",
        lambda body, session, model_id: _response(
            phase="running_jobs",
            assistant_message="Partial results are ready while mailbox delegate scans run.",
        ),
    )

    resp = test_client.post(
        "/api/azure/security/copilot/chat",
        headers={"host": "azure.movedocs.com"},
        json={"message": "Investigate ada@example.com sign-in activity"},
    )

    assert resp.status_code == 200
    assert resp.json()["phase"] == "running_jobs"
    assert "Partial results" in resp.json()["assistant_message"]


def test_security_copilot_route_returns_complete_response(test_client, monkeypatch):
    import routes_azure_security_copilot

    monkeypatch.setattr(
        routes_azure_security_copilot,
        "get_available_copilot_models",
        lambda: [AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama")],
    )
    monkeypatch.setattr(routes_azure_security_copilot, "get_default_copilot_model_id", lambda models: models[0].id)
    monkeypatch.setattr(
        routes_azure_security_copilot,
        "run_security_copilot_chat",
        lambda body, session, model_id: _response(
            phase="complete",
            assistant_message="Investigation complete.",
        ),
    )

    resp = test_client.post(
        "/api/azure/security/copilot/chat",
        headers={"host": "azure.movedocs.com"},
        json={"message": "Investigate suspicious app sign-ins"},
    )

    assert resp.status_code == 200
    assert resp.json()["phase"] == "complete"
    assert resp.json()["answer"]["summary"] == "Completed"
