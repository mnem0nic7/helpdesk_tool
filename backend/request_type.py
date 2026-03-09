"""Helpers for extracting Jira Service Management request type values."""

from __future__ import annotations

from typing import Any, Mapping

_REQUEST_TYPE_FIELD_IDS = ("customfield_10010", "customfield_11102")


def _extract_name_from_field_value(value: Any) -> str:
    """Return a request type name from a Jira custom-field payload."""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""

    # Most common shape:
    # {"requestType": {"name": "Business Application Support", ...}, ...}
    request_type = value.get("requestType")
    if isinstance(request_type, dict):
        for key in ("name", "defaultName", "value"):
            name = request_type.get(key)
            if isinstance(name, str) and name.strip():
                return name.strip()
    elif isinstance(request_type, str) and request_type.strip():
        return request_type.strip()

    # Fallbacks for alternate payloads that directly store a name/value.
    for key in ("name", "defaultName", "value"):
        name = value.get(key)
        if isinstance(name, str) and name.strip():
            return name.strip()

    return ""


def extract_request_type_name_from_fields(fields: Mapping[str, Any]) -> str:
    """Return request type name from known Jira custom fields."""
    for field_id in _REQUEST_TYPE_FIELD_IDS:
        name = _extract_name_from_field_value(fields.get(field_id))
        if name:
            return name
    return ""


def has_request_type(fields: Mapping[str, Any]) -> bool:
    """Return True when request type data is present in either supported field."""
    return bool(extract_request_type_name_from_fields(fields))
