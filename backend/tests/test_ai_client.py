from ai_client import _enforce_security_priority
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
