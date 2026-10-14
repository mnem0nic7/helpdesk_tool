"""Entra -> Jira HR field mapping: pure transforms."""
import hr_entra_field_map as m

EXT = m.EXT_PREFIX


def test_only_enabled_fields_with_jira_ids_are_active():
    active = {x.jira_name for x in m.active_mappings()}
    assert "Job Title" in active and "Business Unit" in active and "Manager Name" in active
    # Fields created from the sheet's "Create" rows are live now.
    assert {"Preferred Name", "Home State", "Position Status", "Seniority Date", "People Manager (Yes/No)"} <= active
    # "Please provide" / suspect rows stay disabled even though they now have Jira ids.
    assert "FLSA Status" not in active
    assert "Legal Middle Name" not in active
    assert "Hire Date" not in active
    assert "Company email address" not in active


def test_every_mapped_jira_field_id_is_unique():
    ids = [x.jira_field_id for x in m.FIELD_MAP if x.jira_field_id]
    assert len(ids) == len(set(ids))


def test_every_disabled_row_explains_itself_or_awaits_a_jira_field():
    for mapping in m.FIELD_MAP:
        if not mapping.enabled:
            assert mapping.note, mapping.jira_name


def test_graph_select_includes_extensions_and_lookup_props_but_not_disabled():
    props = m.graph_select_properties()
    assert f"{EXT}division" in props
    assert {"id", "userPrincipalName", "mail", "otherMails", "manager", "title"} <= set(props)
    assert "employeeId" not in props  # FLSA source is disabled


def test_issue_fields_to_request_includes_lookup_emails():
    ids = m.issue_fields_to_request()
    assert "customfield_12879" in ids and "customfield_12883" in ids


def test_build_issue_fields_text_select_and_manager():
    user = {"title": "Engineer", f"{EXT}division": "Ops", f"{EXT}jobFunction": "IT", "department": ""}
    payload, empty = m.build_issue_fields(user, {"displayName": "Pat Boss", "mail": "pat@x.com"})
    assert payload["customfield_12866"] == "Engineer"
    assert payload["customfield_13458"] == "Ops"
    assert payload["customfield_11113"] == {"value": "IT"}
    assert payload["customfield_15038"] == "Pat Boss"
    assert "Home Department" in empty  # blank string is "no value", never written


def test_no_manager_leaves_manager_name_out():
    payload, empty = m.build_issue_fields({}, None)
    assert "customfield_15038" not in payload
    assert "Manager Name" in empty


def test_parse_date_formats():
    assert m.parse_date("2026-03-01").isoformat() == "2026-03-01"
    assert m.parse_date("2026-03-01T00:00:00Z").isoformat() == "2026-03-01"
    assert m.parse_date("03/01/2026").isoformat() == "2026-03-01"
    assert m.parse_date("20260301").isoformat() == "2026-03-01"
    assert m.parse_date("garbage") is None
    assert m.parse_date("") is None


def test_date_and_datetime_shaping():
    d = m.FieldMapping("d", m.KIND_DATE)
    dt = m.FieldMapping("dt", m.KIND_DATETIME)
    assert m.jira_value(d, "03/01/2026") == "2026-03-01"
    assert m.jira_value(dt, "2026-03-01") == "2026-03-01T00:00:00.000+0000"
    assert m.jira_value(d, "nope") is None


def test_people_manager_yes_no_normalization():
    pm = next(x for x in m.FIELD_MAP if x.jira_name == "People Manager (Yes/No)")
    assert m.jira_value(pm, "true") == {"value": "Yes"}
    assert m.jira_value(pm, "N") == {"value": "No"}
    assert m.jira_value(pm, "maybe") is None


def test_normalize_email_extracts_from_jira_wiki_links_and_plain_text():
    assert m.normalize_email("  Jane.Doe@Example.COM ") == "jane.doe@example.com"
    assert m.normalize_email("[jdoe@x.com|mailto:jdoe@x.com]") == "jdoe@x.com"
    assert m.normalize_email("mailto:jdoe@x.com") == "jdoe@x.com"
    assert m.normalize_email("Jane <jane@x.com>") == "jane@x.com"
    assert m.normalize_email("not-an-email") is None
    assert m.normalize_email(None) is None


def test_normalize_email_keeps_apostrophes_in_local_part():
    assert m.normalize_email("o'brien@x.com") == "o'brien@x.com"
    assert m.normalize_email("'quoted@x.com'") == "quoted@x.com"


def test_function_aliases_map_entra_spellings_to_existing_jira_options():
    fn = next(x for x in m.FIELD_MAP if x.jira_name == "Function")
    assert m.jira_value(fn, "Information Technology") == {"value": "IT"}
    assert m.jira_value(fn, " human resources ") == {"value": "HR"}
    assert m.jira_value(fn, "Operations") == {"value": "Operations"}  # exact option passes through
    assert m.jira_value(fn, "Exec/Admin") == {"value": "Exec/Admin"}  # no Jira option: left for Jira to reject per-field


def test_adp_header_artifacts_are_treated_as_empty():
    fn = next(x for x in m.FIELD_MAP if x.jira_name == "Function")
    assert m.jira_value(fn, "JobFunction") is None
    assert m.jira_value(fn, "JobFunctionDescription") is None
