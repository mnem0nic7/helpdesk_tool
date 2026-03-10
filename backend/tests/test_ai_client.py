import ai_client
from ai_client import _enforce_security_priority, draft_kb_article, score_closed_ticket
from models import KnowledgeBaseArticle, TriageSuggestion


def _issue(priority: str = "Medium", request_type: str | None = None) -> dict:
    fields = {
        "priority": {"name": priority},
    }
    if request_type is not None:
        fields["customfield_10010"] = {"requestType": {"name": request_type}}
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
        "_call_openai",
        lambda model_id, system, user_msg: """{
          "communication_score": 4,
          "communication_notes": "Clear public updates.",
          "documentation_score": 3,
          "documentation_notes": "Resolution steps were partial.",
          "score_summary": "Good communication, average documentation."
        }""",
    )

    score = score_closed_ticket(issue, [{"author": {"displayName": "Ada"}, "body": "Resolved and confirmed.", "public": True}], "gpt-4o-mini")

    assert score.key == "OIT-42"
    assert score.communication_score == 4
    assert score.documentation_score == 3
    assert score.score_summary == "Good communication, average documentation."


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
        "_call_openai",
        lambda model_id, system, user_msg: """{
          "communication_score": 9,
          "communication_notes": "Too generous.",
          "documentation_score": 0,
          "documentation_notes": "Too harsh.",
          "score_summary": "Needs clamping."
        }""",
    )

    score = score_closed_ticket(issue, [], "gpt-4o-mini")

    assert score.communication_score == 5
    assert score.documentation_score == 1


def test_analyze_ticket_includes_relevant_kb_context(monkeypatch):
    captured: dict[str, str] = {}

    def fake_call_openai(model_id, system, user_msg):
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
    monkeypatch.setattr(ai_client, "_call_openai", fake_call_openai)
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

    result = ai_client.analyze_ticket(issue, "gpt-4o-mini")

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
        "_call_openai",
        lambda model_id, system, user_msg: """{
          "title": "Email or Outlook",
          "request_type": "Email or Outlook",
          "summary": "Adds sync repair guidance.",
          "content": "Overview\\n\\nResolution Steps\\n\\nRestart Outlook.",
          "recommended_action": "update_existing",
          "change_summary": "Adds Outlook restart guidance."
        }""",
    )

    draft = draft_kb_article(issue, [], "gpt-4o-mini", existing_article)

    assert draft.title == "Email or Outlook"
    assert draft.recommended_action == "update_existing"
    assert draft.suggested_article_id == 5
    assert "Restart Outlook." in draft.content
