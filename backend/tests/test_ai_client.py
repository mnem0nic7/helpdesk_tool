import ai_client
from ai_client import (
    analyze_ticket,
    _enforce_reporter_hint,
    _enforce_security_priority,
    _extract_reporter_hint_from_text,
    draft_kb_article,
    draft_kb_from_sop,
    get_available_models,
    get_available_copilot_models,
    get_default_copilot_model_id,
    score_closed_ticket,
)
from models import AIModel, KnowledgeBaseArticle, TriageSuggestion


def _issue(
    priority: str = "Medium",
    request_type: str | None = None,
    reporter: str = "OSIJIRAOCC",
    description: str | None = None,
) -> dict:
    fields = {
        "priority": {"name": priority},
        "reporter": {"displayName": reporter},
    }
    if request_type is not None:
        fields["customfield_10010"] = {"requestType": {"name": request_type}}
    if description is not None:
        fields["description"] = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": description}]}
            ],
        }
    return {
        "key": "OIT-1",
        "fields": fields,
    }


def test_security_alert_overrides_low_priority_suggestion_to_high():
    issue = _issue(priority="Low")
    suggestions = [
        TriageSuggestion(
            field="request_type",
            current_value="Get IT help",
            suggested_value="Security Alert",
            reasoning="Phishing indicators in the ticket body.",
            confidence=0.95,
        ),
        TriageSuggestion(
            field="priority",
            current_value="Low",
            suggested_value="Medium",
            reasoning="General triage guess.",
            confidence=0.62,
        ),
    ]

    normalized = _enforce_security_priority(issue, suggestions)

    priority = next(s for s in normalized if s.field == "priority")
    assert priority.suggested_value == "High"
    assert priority.current_value == "Low"
    assert priority.confidence >= 0.99


def test_security_alert_adds_high_priority_when_missing():
    issue = _issue(priority="New")
    suggestions = [
        TriageSuggestion(
            field="request_type",
            current_value="Get IT help",
            suggested_value="Security Alert",
            reasoning="Threat report matched the security category.",
            confidence=0.97,
        ),
    ]

    normalized = _enforce_security_priority(issue, suggestions)

    priority = next(s for s in normalized if s.field == "priority")
    assert priority.suggested_value == "High"
    assert priority.current_value == "New"


def test_existing_high_security_ticket_does_not_get_priority_change():
    issue = _issue(priority="Highest", request_type="Security Alert")
    suggestions = [
        TriageSuggestion(
            field="request_type",
            current_value="Security Alert",
            suggested_value="Security Alert",
            reasoning="Already correctly classified.",
            confidence=0.99,
        ),
        TriageSuggestion(
            field="priority",
            current_value="Highest",
            suggested_value="High",
            reasoning="Model tried to normalize the value.",
            confidence=0.88,
        ),
    ]

    normalized = _enforce_security_priority(issue, suggestions)

    assert all(s.field != "priority" for s in normalized)


def test_extract_reporter_hint_from_occ_created_by_text():
    text = "OCC Ticket Created By: Raza Abidi |\n*Caution* External email."
    assert _extract_reporter_hint_from_text(text) == "Raza Abidi"


def test_enforce_reporter_hint_adds_reporter_suggestion():
    issue = _issue(description="OCC Ticket Created By: Raza Abidi |")

    normalized = _enforce_reporter_hint(issue, [])

    reporter = next(s for s in normalized if s.field == "reporter")
    assert reporter.current_value == "OSIJIRAOCC"
    assert reporter.suggested_value == "Raza Abidi"
    assert reporter.confidence >= 0.99


def test_get_available_copilot_models_requires_ollama_runtime(monkeypatch):
    monkeypatch.setattr(ai_client, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ai_client, "OLLAMA_ENABLED", False)

    models = get_available_copilot_models()

    assert models == []


def test_get_available_models_includes_ollama_when_enabled(monkeypatch):
    monkeypatch.setattr(ai_client, "OPENAI_API_KEY", "")
    monkeypatch.setattr(ai_client, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(ai_client, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(ai_client, "OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setattr(ai_client, "_OLLAMA_MODEL_CACHE", None)
    monkeypatch.setattr(
        ai_client,
        "_list_ollama_models_from_api",
        lambda: [
            AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama"),
            AIModel(id="qwen2.5:3b", name="qwen2.5:3b", provider="ollama"),
        ],
    )

    models = get_available_models()

    assert [model.id for model in models] == ["qwen2.5:7b", "qwen2.5:3b"]


def test_get_available_models_ignores_cloud_keys_and_uses_ollama_only(monkeypatch):
    monkeypatch.setattr(ai_client, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ai_client, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai_client, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(ai_client, "_OLLAMA_MODEL_CACHE", None)
    monkeypatch.setattr(
        ai_client,
        "_list_ollama_models_from_api",
        lambda: [AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama")],
    )

    models = get_available_models()

    assert [model.provider for model in models] == ["ollama"]


def test_invoke_model_text_rejects_non_ollama_models(monkeypatch):
    monkeypatch.setattr(ai_client, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(ai_client, "_OLLAMA_MODEL_CACHE", None)
    monkeypatch.setattr(ai_client, "_list_ollama_models_from_api", lambda: [AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama")])

    try:
        ai_client.invoke_model_text(
            "gpt-4o",
            "system prompt",
            "user prompt",
            feature_surface="ticket_auto_triage",
            app_surface="tickets",
        )
    except ValueError as exc:
        assert "Unknown model" in str(exc)
    else:
        raise AssertionError("Expected invoke_model_text to reject non-Ollama models")


def test_get_default_copilot_model_id_prefers_supported_default():
    models = [
        AIModel(id="gpt-3.5-turbo", name="gpt-3.5-turbo", provider="openai"),
        AIModel(id="gpt-5.4-mini", name="gpt-5.4-mini", provider="openai"),
    ]

    assert get_default_copilot_model_id(models) == "gpt-5.4-mini"


def test_score_closed_ticket_parses_scores(monkeypatch):
    issue = {
        "key": "OIT-42",
        "fields": {
            "summary": "Closed ticket",
            "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
            "resolution": {"name": "Done"},
            "resolutiondate": "2026-03-03T10:00:00Z",
            "assignee": {"displayName": "Ada"},
            "comment": {"comments": []},
        },
    }

    monkeypatch.setattr(
        ai_client,
        "invoke_model_text",
        lambda model_id, system, user_msg, **kwargs: """{
          "communication_score": 4,
          "communication_notes": "Clear public updates.",
          "documentation_score": 3,
          "documentation_notes": "Resolution steps were partial.",
          "score_summary": "Good communication, average documentation."
        }""",
    )
    monkeypatch.setattr(ai_client, "_get_model_provider", lambda model_id: "ollama")

    score = score_closed_ticket(issue, [{"author": {"displayName": "Ada"}, "body": "Resolved and confirmed.", "public": True}], "qwen2.5:7b")

    assert score.key == "OIT-42"
    assert score.communication_score == 4
    assert score.documentation_score == 3
    assert score.score_summary == "Good communication, average documentation."


def test_analyze_ticket_uses_ollama_provider(monkeypatch):
    issue = {
        "key": "OIT-314",
        "fields": {
            "summary": "VPN not connecting",
            "priority": {"name": "Medium"},
            "status": {"name": "Open"},
            "description": {
                "type": "doc",
                "content": [{"type": "text", "text": "User cannot connect to the VPN from home."}],
            },
            "comment": {"comments": []},
        },
    }

    monkeypatch.setattr(ai_client, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(ai_client, "OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setattr(ai_client, "get_request_type_names", lambda: ["VPN", "Get IT help"])
    monkeypatch.setattr(
        ai_client,
        "invoke_model_text",
        lambda model_id, system, user_msg, **kwargs: """{
          "suggestions": [
            {
              "field": "request_type",
              "suggested_value": "VPN",
              "reasoning": "Ticket clearly describes a VPN connectivity issue.",
              "confidence": 0.97
            }
          ]
        }""",
    )
    import knowledge_base

    monkeypatch.setattr(knowledge_base.kb_store, "find_relevant_articles", lambda **kwargs: [])

    result = analyze_ticket(issue, "qwen2.5:7b")

    assert result.model_used == "qwen2.5:7b"
    assert result.suggestions[0].field == "request_type"
    assert result.suggestions[0].suggested_value == "VPN"


def test_score_closed_ticket_clamps_invalid_scores(monkeypatch):
    issue = {
        "key": "OIT-77",
        "fields": {
            "summary": "Closed ticket",
            "status": {"name": "Closed", "statusCategory": {"name": "Done"}},
            "comment": {"comments": []},
        },
    }

    monkeypatch.setattr(
        ai_client,
        "invoke_model_text",
        lambda model_id, system, user_msg, **kwargs: """{
          "communication_score": 9,
          "communication_notes": "Too generous.",
          "documentation_score": 0,
          "documentation_notes": "Too harsh.",
          "score_summary": "Needs clamping."
        }""",
    )
    monkeypatch.setattr(ai_client, "_get_model_provider", lambda model_id: "ollama")

    score = score_closed_ticket(issue, [], "qwen2.5:7b")

    assert score.communication_score == 5
    assert score.documentation_score == 1


def test_analyze_ticket_includes_relevant_kb_context(monkeypatch):
    captured: dict[str, str] = {}

    def fake_invoke_model_text(model_id, system, user_msg, **kwargs):
        captured["user_msg"] = user_msg
        return """{
          "suggestions": [
            {
              "field": "request_type",
              "suggested_value": "Email or Outlook",
              "reasoning": "Outlook email issue.",
              "confidence": 0.95
            }
          ]
        }"""

    issue = {
        "key": "OIT-99",
        "fields": {
            "summary": "Outlook cannot send mail",
            "priority": {"name": "Medium"},
            "status": {"name": "Open"},
            "description": {
                "type": "doc",
                "content": [{"type": "text", "text": "User cannot send messages in Outlook."}],
            },
            "comment": {"comments": []},
            "customfield_10010": {"requestType": {"name": "Email or Outlook"}},
        },
    }

    monkeypatch.setattr(ai_client, "get_request_type_names", lambda: ["Email or Outlook", "Get IT help"])
    monkeypatch.setattr(ai_client, "invoke_model_text", fake_invoke_model_text)
    monkeypatch.setattr(ai_client, "_get_model_provider", lambda model_id: "ollama")
    import knowledge_base
    monkeypatch.setattr(
        knowledge_base.kb_store,
        "find_relevant_articles",
        lambda **kwargs: [
            KnowledgeBaseArticle(
                id=1,
                slug="email-or-outlook",
                code="KB-EML-001",
                title="Email or Outlook",
                request_type="Email or Outlook",
                summary="Mailbox troubleshooting guide.",
                content="Restart Outlook and verify Exchange connectivity.",
                source_filename="KB-EML-001_Email_or_Outlook.docx",
                source_ticket_key="",
                imported_from_seed=True,
                ai_generated=False,
                created_at="2026-03-10T00:00:00Z",
                updated_at="2026-03-10T00:00:00Z",
            )
        ],
    )

    result = ai_client.analyze_ticket(issue, "qwen2.5:7b")

    assert result.suggestions[0].suggested_value == "Email or Outlook"
    assert "Relevant Knowledge Base Articles" in captured["user_msg"]
    assert "Restart Outlook and verify Exchange connectivity." in captured["user_msg"]


def test_draft_kb_article_parses_model_response(monkeypatch):
    issue = {
        "key": "OIT-42",
        "fields": {
            "summary": "Closed Outlook issue",
            "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
            "customfield_10010": {"requestType": {"name": "Email or Outlook"}},
            "comment": {"comments": []},
        },
    }
    existing_article = KnowledgeBaseArticle(
        id=5,
        slug="email-or-outlook",
        code="KB-EML-001",
        title="Email or Outlook",
        request_type="Email or Outlook",
        summary="Mailbox troubleshooting guide.",
        content="Existing article body.",
        source_filename="KB-EML-001_Email_or_Outlook.docx",
        source_ticket_key="",
        imported_from_seed=True,
        ai_generated=False,
        created_at="2026-03-10T00:00:00Z",
        updated_at="2026-03-10T00:00:00Z",
    )

    monkeypatch.setattr(
        ai_client,
        "invoke_model_text",
        lambda model_id, system, user_msg, **kwargs: """{
          "title": "Email or Outlook",
          "request_type": "Email or Outlook",
          "summary": "Adds sync repair guidance.",
          "content": "Overview\\n\\nResolution Steps\\n\\nRestart Outlook.",
          "recommended_action": "update_existing",
          "change_summary": "Adds Outlook restart guidance."
        }""",
    )
    monkeypatch.setattr(ai_client, "_get_model_provider", lambda model_id: "ollama")

    draft = draft_kb_article(issue, [], "qwen2.5:7b", existing_article)

    assert draft.title == "Email or Outlook"
    assert draft.recommended_action == "update_existing"
    assert draft.suggested_article_id == 5
    assert "Restart Outlook." in draft.content


def test_draft_kb_from_sop_supports_ollama(monkeypatch):
    monkeypatch.setattr(ai_client, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(ai_client, "OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setattr(
        ai_client,
        "invoke_model_text",
        lambda model_id, system, user_msg, **kwargs: """{
          "title": "VPN Access",
          "request_type": "VPN",
          "summary": "Steps to restore VPN access.",
          "content": "1. Verify FortiClient settings.",
          "change_summary": "Converted from SOP"
        }""",
    )

    draft = draft_kb_from_sop("VPN troubleshooting steps", "vpn_access.docx", "qwen2.5:7b")

    assert draft.title == "VPN Access"
    assert draft.model_used == "qwen2.5:7b"
    assert draft.request_type == "VPN"


def test_invoke_model_text_records_ai_usage(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(ai_client, "_get_model_provider", lambda model_id: "ollama")
    monkeypatch.setattr(ai_client, "AZURE_FINOPS_AI_TEAM_MAPPINGS", {})
    monkeypatch.setattr(
        ai_client,
        "_invoke_ollama",
        lambda model_id, system, user_msg, **kwargs: ("structured output", {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}),
    )
    monkeypatch.setattr(
        ai_client.azure_finops_service,
        "record_ai_usage",
        lambda **kwargs: recorded.update(kwargs) or {"usage_id": "usage-1"},
    )

    result = ai_client.invoke_model_text(
        "qwen2.5:7b",
        "system prompt",
        "user prompt",
        feature_surface="azure_cost_copilot",
        app_surface="azure_portal",
        actor_type="user",
        actor_id="tester@example.com",
    )

    assert result == "structured output"
    assert recorded["feature_surface"] == "azure_cost_copilot"
    assert recorded["app_surface"] == "azure_portal"
    assert recorded["provider"] == "ollama"
    assert recorded["input_tokens"] == 12
    assert recorded["output_tokens"] == 8
    assert recorded["team"] == "FinOps"
    assert recorded["metadata"]["team_source"] == "default_feature_surface"
    assert recorded["metadata"]["team_source_key"] == "azure_cost_copilot"


def test_invoke_model_text_prefers_explicit_team_over_mappings(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(ai_client, "_get_model_provider", lambda model_id: "ollama")
    monkeypatch.setattr(
        ai_client,
        "AZURE_FINOPS_AI_TEAM_MAPPINGS",
        {"feature_surfaces": {"azure_cost_copilot": "FinOps"}},
    )
    monkeypatch.setattr(
        ai_client,
        "_invoke_ollama",
        lambda model_id, system, user_msg, **kwargs: ("structured output", {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
    )
    monkeypatch.setattr(
        ai_client.azure_finops_service,
        "record_ai_usage",
        lambda **kwargs: recorded.update(kwargs) or {"usage_id": "usage-2"},
    )

    ai_client.invoke_model_text(
        "qwen2.5:7b",
        "system prompt",
        "user prompt",
        feature_surface="azure_cost_copilot",
        app_surface="azure_portal",
        actor_type="user",
        actor_id="owner@example.com",
        team="Cloud Operations",
    )

    assert recorded["team"] == "Cloud Operations"
    assert recorded["metadata"]["team_source"] == "explicit"
    assert "team_source_key" not in recorded["metadata"]


def test_invoke_model_text_uses_actor_mapping_before_defaults(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(ai_client, "_get_model_provider", lambda model_id: "ollama")
    monkeypatch.setattr(
        ai_client,
        "AZURE_FINOPS_AI_TEAM_MAPPINGS",
        {"actor_ids": {"tester@example.com": "Executive IT"}},
    )
    monkeypatch.setattr(
        ai_client,
        "_invoke_ollama",
        lambda model_id, system, user_msg, **kwargs: ("structured output", {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
    )
    monkeypatch.setattr(
        ai_client.azure_finops_service,
        "record_ai_usage",
        lambda **kwargs: recorded.update(kwargs) or {"usage_id": "usage-3"},
    )

    ai_client.invoke_model_text(
        "qwen2.5:7b",
        "system prompt",
        "user prompt",
        feature_surface="ticket_auto_triage",
        app_surface="tickets",
        actor_type="user",
        actor_id="tester@example.com",
    )

    assert recorded["team"] == "Executive IT"
    assert recorded["metadata"]["team_source"] == "actor_id"
    assert recorded["metadata"]["team_source_key"] == "tester@example.com"
