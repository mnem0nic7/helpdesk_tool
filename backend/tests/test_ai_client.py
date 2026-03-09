import ai_client
from ai_client import _enforce_security_priority, score_closed_ticket
from models import TriageSuggestion


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
