from request_type import (
    extract_request_type_id_from_fields,
    extract_request_type_name_from_fields,
    has_request_type,
)


def test_extract_from_customfield_10010_request_type():
    fields = {
        "customfield_10010": {
            "requestType": {"id": "17", "name": "VPN"},
        }
    }
    assert extract_request_type_name_from_fields(fields) == "VPN"
    assert extract_request_type_id_from_fields(fields) == "17"
    assert has_request_type(fields) is True


def test_extract_from_customfield_11102_request_type():
    fields = {
        "customfield_11102": {
            "requestType": {"id": "42", "name": "Business Application Support"},
        }
    }
    assert extract_request_type_name_from_fields(fields) == "Business Application Support"
    assert extract_request_type_id_from_fields(fields) == "42"
    assert has_request_type(fields) is True


def test_extract_from_direct_string_value():
    fields = {"customfield_11102": "Email or Outlook"}
    assert extract_request_type_name_from_fields(fields) == "Email or Outlook"
    assert extract_request_type_id_from_fields(fields) == ""
    assert has_request_type(fields) is True


def test_extract_prefers_primary_field_order():
    fields = {
        "customfield_10010": {"requestType": {"id": "9", "name": "Security Alert"}},
        "customfield_11102": {"requestType": {"id": "5", "name": "Get IT help"}},
    }
    assert extract_request_type_name_from_fields(fields) == "Security Alert"
    assert extract_request_type_id_from_fields(fields) == "9"
