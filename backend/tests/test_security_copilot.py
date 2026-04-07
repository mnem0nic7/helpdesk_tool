from __future__ import annotations

from unittest.mock import MagicMock

import security_copilot
from models import (
    AzureCitation,
    SecurityCopilotChatRequest,
    SecurityCopilotChatMessage,
    SecurityCopilotIncident,
    SecurityCopilotJobRef,
)
from security_copilot import SecuritySourceDefinition


def test_resolve_incident_profile_falls_back_to_heuristics(monkeypatch):
    monkeypatch.setattr(
        security_copilot,
        "invoke_model_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ollama unavailable")),
    )

    incident = security_copilot._resolve_incident_profile(
        "Shared mailbox payroll@example.com is forwarding mail externally since 2 AM UTC.",
        SecurityCopilotIncident(),
        "nemotron-3-nano:4b",
    )

    assert incident.lane == "mailbox_abuse"
    assert "payroll@example.com" in incident.affected_mailboxes
    assert incident.timeframe


def test_resolve_incident_profile_classifies_dlp_findings(monkeypatch):
    monkeypatch.setattr(
        security_copilot,
        "invoke_model_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ollama unavailable")),
    )

    incident = security_copilot._resolve_incident_profile(
        "Purview DLP alert blocked payroll@example.com from emailing employee SSNs outside the organization this morning.",
        SecurityCopilotIncident(),
        "nemotron-3-nano:4b",
    )

    assert incident.lane == "dlp_finding"
    assert "payroll@example.com" in incident.affected_users
    assert "payroll@example.com" in incident.affected_mailboxes
    assert incident.timeframe


def test_resolve_incident_profile_includes_recent_chat_history_in_model_payload(monkeypatch):
    captured: dict[str, object] = {}

    def fake_invoke_model_text(*args, **kwargs):
        captured["payload"] = kwargs.get("user_message") if "user_message" in kwargs else args[2]
        return """
        {
          "lane": "identity_compromise",
          "summary": "Investigate ada@example.com sign-ins",
          "timeframe": "Since 2 AM UTC",
          "affected_users": ["ada@example.com"],
          "affected_mailboxes": ["ada@example.com"],
          "affected_apps": [],
          "affected_resources": [],
          "alert_names": [],
          "observed_artifacts": [],
          "confidence": 0.82
        }
        """

    monkeypatch.setattr(security_copilot, "invoke_model_text", fake_invoke_model_text)

    incident = security_copilot._resolve_incident_profile(
        "Check her account first.",
        SecurityCopilotIncident(),
        "nemotron-3-nano:4b",
        history=[
            SecurityCopilotChatMessage(role="user", content="ada@example.com reported impossible travel alerts."),
            SecurityCopilotChatMessage(role="assistant", content="I still need the timeframe."),
        ],
    )

    payload = security_copilot._extract_json_object(str(captured["payload"]))
    assert payload["recent_history"][0]["content"] == "ada@example.com reported impossible travel alerts."
    assert incident.affected_users == ["ada@example.com"]
    assert incident.timeframe == "Since 2 AM UTC"


def test_run_security_copilot_chat_resolves_display_name_to_identity_confirmation(monkeypatch):
    monkeypatch.setattr(
        security_copilot,
        "invoke_model_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ollama unavailable")),
    )
    monkeypatch.setattr(
        security_copilot.azure_cache,
        "list_directory_objects",
        lambda snapshot_name, *, search="": [
            {
                "id": "user-1",
                "display_name": "Abhishek Mishra",
                "principal_name": "abhishek.mishra@example.com",
                "mail": "abhishek.mishra@example.com",
            }
        ]
        if snapshot_name == "users" and "abhishek mishra" in search.lower()
        else [],
    )
    monkeypatch.setattr(security_copilot, "_build_source_registry", lambda: [])

    response = security_copilot.run_security_copilot_chat(
        SecurityCopilotChatRequest(
            message="Abhishek Mishra had impossible travel in the last two week investigate and report back with findings",
            incident=SecurityCopilotIncident(),
        ),
        {"email": "test@example.com", "name": "Test User"},
        model_id="nemotron-3-nano:4b",
    )

    assert response.phase == "needs_input"
    assert response.incident.identity_query == "Abhishek Mishra"
    assert response.incident.identity_candidates[0].principal_name == "abhishek.mishra@example.com"
    assert response.follow_up_questions[0].key == "identity_confirmation"
    assert response.follow_up_questions[0].choices == ["Abhishek Mishra <abhishek.mishra@example.com>"]
    assert "Confirm which account I should investigate first" in response.assistant_message


def test_resolve_incident_profile_accepts_identity_confirmation_reply(monkeypatch):
    monkeypatch.setattr(
        security_copilot,
        "invoke_model_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ollama unavailable")),
    )

    incident = security_copilot._resolve_incident_profile(
        "the first one",
        SecurityCopilotIncident(
            lane="identity_compromise",
            summary="Abhishek Mishra had impossible travel.",
            timeframe="last two weeks",
            identity_query="Abhishek Mishra",
            identity_candidates=[
                security_copilot.SecurityCopilotIdentityCandidate(
                    id="user-1",
                    display_name="Abhishek Mishra",
                    principal_name="abhishek.mishra@example.com",
                    mail="abhishek.mishra@example.com",
                    match_reason="display_name_exact",
                )
            ],
        ),
        "nemotron-3-nano:4b",
    )

    assert incident.summary == "Abhishek Mishra had impossible travel."
    assert incident.affected_users == ["abhishek.mishra@example.com"]
    assert incident.identity_candidates == []
    assert incident.identity_query == ""
    assert "identity_confirmation" not in incident.missing_fields


def test_plan_security_sources_skips_user_admin_without_permission():
    incident = SecurityCopilotIncident(
        lane="identity_compromise",
        summary="Compromised user investigation",
        timeframe="Since 2 AM UTC",
        affected_users=["ada@example.com"],
    )
    session = {"auth_provider": "atlassian", "can_manage_users": False}

    planned = security_copilot.plan_security_sources(incident, session)
    user_admin = next(item for item in planned if item.key == "user_admin")

    assert user_admin.status == "skipped"
    assert "user-admin access" in user_admin.reason


def test_plan_security_sources_includes_dlp_relevant_sources():
    incident = SecurityCopilotIncident(
        lane="dlp_finding",
        summary="Purview DLP blocked payroll@example.com from sending W-2 data externally.",
        timeframe="This morning",
        affected_users=["payroll@example.com"],
        affected_mailboxes=["payroll@example.com"],
        observed_artifacts=["SSN"],
    )
    session = {"auth_provider": "atlassian", "can_manage_users": True}

    planned = security_copilot.plan_security_sources(incident, session)
    planned_keys = {item.key for item in planned}

    assert "directory" in planned_keys
    assert "login_audit" in planned_keys
    assert "mailbox_rules" in planned_keys
    assert "delegate_mailbox_scan_job" in planned_keys
    assert "ticket_search" in planned_keys


def test_run_security_copilot_chat_returns_needs_input_for_missing_fields(monkeypatch):
    monkeypatch.setattr(security_copilot, "_build_source_registry", lambda: [])

    response = security_copilot.run_security_copilot_chat(
        SecurityCopilotChatRequest(
            message="",
            incident=SecurityCopilotIncident(
                lane="mailbox_abuse",
                summary="Shared mailbox is sending suspicious mail.",
            ),
        ),
        {"email": "test@example.com", "name": "Test User"},
        model_id="nemotron-3-nano:4b",
    )

    assert response.phase == "needs_input"
    assert any(question.key == "timeframe" for question in response.follow_up_questions)
    assert any(question.key == "affected_mailboxes" for question in response.follow_up_questions)


def test_run_security_copilot_chat_reports_source_errors(monkeypatch):
    def broken_runner(incident, session, jobs):
        raise RuntimeError("source exploded")

    monkeypatch.setattr(
        security_copilot,
        "_build_source_registry",
        lambda: [
            SecuritySourceDefinition(
                key="broken",
                label="Broken source",
                permission="authenticated",
                applies=lambda incident: True,
                query_summary=lambda incident: "broken source query",
                runner=broken_runner,
            )
        ],
    )
    monkeypatch.setattr(
        security_copilot,
        "invoke_model_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthesis unavailable")),
    )

    response = security_copilot.run_security_copilot_chat(
        SecurityCopilotChatRequest(
            message="",
            incident=SecurityCopilotIncident(
                lane="unknown",
                summary="Suspicious incident",
                timeframe="Today",
                observed_artifacts=["198.51.100.10"],
            ),
        ),
        {"email": "test@example.com", "name": "Test User"},
        model_id="nemotron-3-nano:4b",
    )

    assert response.phase == "complete"
    assert response.source_results[0].status == "error"
    assert "source exploded" in response.source_results[0].reason
    assert response.answer.summary


def test_run_security_copilot_chat_returns_running_jobs(monkeypatch):
    def running_job_runner(incident, session, jobs):
        job = SecurityCopilotJobRef(
            job_type="delegate_mailbox_scan",
            label="Delegate mailbox scan",
            job_id="delegate-job-1",
            status="running",
            phase="scanning_exchange_permissions",
            target="ada@example.com",
            summary="Scanning exchange permissions",
            started_automatically=True,
        )
        result = security_copilot._result(
            key="delegate_mailbox_scan_job",
            label="Delegate mailbox scan job",
            status="running",
            query_summary="ada@example.com",
            item_count=1,
            highlights=["ada@example.com: running (scanning exchange permissions)"],
            citations=[
                AzureCitation(
                    source_type="delegate_mailbox_scan",
                    label="Delegate mailbox scan",
                    detail="1 running job",
                )
            ],
        )
        return result, [job]

    monkeypatch.setattr(
        security_copilot,
        "_build_source_registry",
        lambda: [
            SecuritySourceDefinition(
                key="delegate_mailbox_scan_job",
                label="Delegate mailbox scan job",
                permission="authenticated",
                applies=lambda incident: True,
                query_summary=lambda incident: "ada@example.com",
                runner=running_job_runner,
            )
        ],
    )

    response = security_copilot.run_security_copilot_chat(
        SecurityCopilotChatRequest(
            message="",
            incident=SecurityCopilotIncident(
                lane="identity_compromise",
                summary="Investigate possible compromise",
                timeframe="Today",
                affected_users=["ada@example.com"],
            ),
        ),
        {"email": "test@example.com", "name": "Test User"},
        model_id="nemotron-3-nano:4b",
    )

    assert response.phase == "running_jobs"
    assert response.jobs[0].job_id == "delegate-job-1"
    assert response.source_results[0].status == "running"


def test_run_security_copilot_chat_warns_when_tenant_data_is_stale(monkeypatch):
    mock_azure_cache = MagicMock()
    mock_azure_cache.status.return_value = {
        "configured": True,
        "initialized": True,
        "refreshing": False,
        "last_refresh": "2026-03-20T00:00:00Z",
        "datasets": [
            {"configured": True, "error": "", "label": "Directory"},
        ],
    }
    mock_azure_cache.get_overview.return_value = {
        "subscriptions": 1,
        "resources": 2,
        "users": 3,
        "directory_roles": 1,
    }
    monkeypatch.setattr(security_copilot, "azure_cache", mock_azure_cache)
    monkeypatch.setattr(
        security_copilot,
        "_build_source_registry",
        lambda: [
            SecuritySourceDefinition(
                key="tenant_status",
                label="Azure tenant status",
                permission="authenticated",
                applies=lambda incident: True,
                query_summary=lambda incident: "tenant status",
                runner=security_copilot._run_tenant_status_source,
            )
        ],
    )
    monkeypatch.setattr(
        security_copilot,
        "invoke_model_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthesis unavailable")),
    )

    response = security_copilot.run_security_copilot_chat(
        SecurityCopilotChatRequest(
            message="",
            incident=SecurityCopilotIncident(
                lane="unknown",
                summary="Check tenant health",
                timeframe="Today",
                observed_artifacts=["alert"],
            ),
        ),
        {"email": "test@example.com", "name": "Test User"},
        model_id="nemotron-3-nano:4b",
    )

    assert response.phase == "complete"
    assert response.source_results[0].reason == "Azure cache data is older than 4 hours."
    assert any("stale" in warning.lower() for warning in response.answer.warnings)


def test_run_security_copilot_chat_handles_no_relevant_findings(monkeypatch):
    def empty_runner(incident, session, jobs):
        return (
            security_copilot._result(
                key="kb",
                label="Knowledge base",
                status="completed",
                query_summary="security alert",
                item_count=0,
                highlights=["No matching internal knowledge-base articles were found."],
            ),
            jobs,
        )

    monkeypatch.setattr(
        security_copilot,
        "_build_source_registry",
        lambda: [
            SecuritySourceDefinition(
                key="kb",
                label="Knowledge base",
                permission="authenticated",
                applies=lambda incident: True,
                query_summary=lambda incident: "security alert",
                runner=empty_runner,
            )
        ],
    )
    monkeypatch.setattr(
        security_copilot,
        "invoke_model_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthesis unavailable")),
    )

    response = security_copilot.run_security_copilot_chat(
        SecurityCopilotChatRequest(
            message="",
            incident=SecurityCopilotIncident(
                lane="unknown",
                summary="Unknown incident",
                timeframe="Today",
                observed_artifacts=["198.51.100.10"],
            ),
        ),
        {"email": "test@example.com", "name": "Test User"},
        model_id="nemotron-3-nano:4b",
    )

    assert response.phase == "complete"
    assert response.answer.findings[0] == "No high-confidence findings were returned from the currently available sources."
