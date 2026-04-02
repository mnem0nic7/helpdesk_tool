from __future__ import annotations

from models import (
    SecurityAccessReviewAssignment,
    SecurityAccessReviewBreakGlassCandidate,
    SecurityAccessReviewMetric,
    SecurityAccessReviewPrincipal,
    SecurityAccessReviewResponse,
    SecurityAppHygieneApp,
    SecurityAppHygieneCredential,
    SecurityAppHygieneMetric,
    SecurityAppHygieneResponse,
    SecurityBreakGlassValidationAccount,
    SecurityBreakGlassValidationResponse,
    SecurityDirectoryRoleReviewMembership,
    SecurityDirectoryRoleReviewResponse,
    SecurityDirectoryRoleReviewRole,
)


def _response() -> SecurityAccessReviewResponse:
    return SecurityAccessReviewResponse(
        generated_at="2026-04-02T02:00:00Z",
        inventory_last_refresh="2026-04-02T01:55:00Z",
        directory_last_refresh="2026-04-02T01:56:00Z",
        metrics=[
            SecurityAccessReviewMetric(
                key="privileged_principals",
                label="Privileged principals",
                value=3,
                detail="Three principals need review.",
                tone="sky",
            )
        ],
        flagged_principals=[
            SecurityAccessReviewPrincipal(
                principal_id="user-1",
                principal_type="User",
                object_type="user",
                display_name="Emergency Admin",
                principal_name="emergency-admin@example.com",
                enabled=True,
                user_type="Member",
                last_successful_utc="2026-04-01T00:00:00Z",
                role_names=["Owner"],
                assignment_count=1,
                scope_count=1,
                highest_privilege="critical",
                flags=["Assignment is scoped at the subscription root."],
                subscriptions=["Prod"],
            )
        ],
        assignments=[
            SecurityAccessReviewAssignment(
                assignment_id="assignment-1",
                principal_id="user-1",
                principal_type="User",
                object_type="user",
                display_name="Emergency Admin",
                principal_name="emergency-admin@example.com",
                role_definition_id="owner-role",
                role_name="Owner",
                privilege_level="critical",
                scope="/subscriptions/sub-1",
                subscription_id="sub-1",
                subscription_name="Prod",
                enabled=True,
                user_type="Member",
                last_successful_utc="2026-04-01T00:00:00Z",
                flags=["Assignment is scoped at the subscription root."],
            )
        ],
        break_glass_candidates=[
            SecurityAccessReviewBreakGlassCandidate(
                user_id="user-1",
                display_name="Emergency Admin",
                principal_name="emergency-admin@example.com",
                enabled=True,
                last_successful_utc="2026-04-01T00:00:00Z",
                matched_terms=["Emergency naming"],
                privileged_assignment_count=1,
                has_privileged_access=True,
                flags=["Account currently holds privileged Azure RBAC access."],
            )
        ],
        warnings=[],
        scope_notes=["This v1 review focuses on Azure RBAC role assignments from the cached inventory dataset."],
    )


def _app_hygiene_response() -> SecurityAppHygieneResponse:
    return SecurityAppHygieneResponse(
        generated_at="2026-04-02T02:00:00Z",
        directory_last_refresh="2026-04-02T01:56:00Z",
        metrics=[
            SecurityAppHygieneMetric(
                key="expired_credentials",
                label="Expired credentials",
                value=2,
                detail="Two credentials are expired.",
                tone="rose",
            )
        ],
        flagged_apps=[
            SecurityAppHygieneApp(
                application_id="app-1",
                app_id="00000000-1111-2222-3333-444444444444",
                display_name="Payroll Connector",
                sign_in_audience="AzureADMyOrg",
                created_datetime="2025-01-10T00:00:00Z",
                publisher_domain="contoso.com",
                verified_publisher_name="",
                owner_count=0,
                owners=[],
                owner_lookup_error="",
                credential_count=1,
                password_credential_count=1,
                key_credential_count=0,
                next_credential_expiry="2026-04-20T00:00:00Z",
                expired_credential_count=1,
                expiring_30d_count=0,
                expiring_90d_count=0,
                status="critical",
                flags=["1 credential is already expired."],
            )
        ],
        credentials=[
            SecurityAppHygieneCredential(
                application_id="app-1",
                app_id="00000000-1111-2222-3333-444444444444",
                application_display_name="Payroll Connector",
                credential_type="secret",
                display_name="Prod secret",
                key_id="secret-1",
                start_date_time="2025-01-01T00:00:00Z",
                end_date_time="2026-03-01T00:00:00Z",
                days_until_expiry=-10,
                status="expired",
                owner_count=0,
                owners=[],
                flags=["Credential is already expired."],
            )
        ],
        warnings=[],
        scope_notes=["This v1 review uses cached app registration metadata from Microsoft Graph."],
    )


def _break_glass_response() -> SecurityBreakGlassValidationResponse:
    return SecurityBreakGlassValidationResponse(
        generated_at="2026-04-02T02:00:00Z",
        inventory_last_refresh="2026-04-02T01:55:00Z",
        directory_last_refresh="2026-04-02T01:56:00Z",
        metrics=[
            SecurityAccessReviewMetric(
                key="matched_accounts",
                label="Matched accounts",
                value=2,
                detail="Two candidates matched the naming rules.",
                tone="sky",
            )
        ],
        accounts=[
            SecurityBreakGlassValidationAccount(
                user_id="user-1",
                display_name="Emergency Admin",
                principal_name="emergency-admin@example.com",
                enabled=True,
                user_type="Member",
                account_class="person_cloud",
                matched_terms=["Emergency naming"],
                has_privileged_access=True,
                privileged_assignment_count=1,
                last_successful_utc="2026-04-01T00:00:00Z",
                days_since_last_successful=1,
                last_password_change="2026-03-01T00:00:00Z",
                days_since_password_change=32,
                is_licensed=False,
                license_count=0,
                on_prem_sync=False,
                status="healthy",
                flags=["Account currently holds 1 privileged Azure RBAC assignment."],
            )
        ],
        warnings=["MFA registration posture is not cached in this workspace yet."],
        scope_notes=["This lane reuses the same break-glass naming heuristics as the Privileged Access Review lane."],
    )


def _directory_role_review_response(_session=None) -> SecurityDirectoryRoleReviewResponse:
    return SecurityDirectoryRoleReviewResponse(
        generated_at="2026-04-02T02:00:00Z",
        directory_last_refresh="2026-04-02T01:56:00Z",
        access_available=True,
        access_message="Live direct role review is available.",
        metrics=[
            SecurityAccessReviewMetric(
                key="roles_with_members",
                label="Roles with direct members",
                value=2,
                detail="Two roles currently have direct members.",
                tone="sky",
            )
        ],
        roles=[
            SecurityDirectoryRoleReviewRole(
                role_id="role-1",
                display_name="Global Administrator",
                description="Full tenant access.",
                privilege_level="critical",
                member_count=3,
                flagged_member_count=3,
                flags=["Membership list was truncated to the first 100 results."],
            )
        ],
        memberships=[
            SecurityDirectoryRoleReviewMembership(
                role_id="role-1",
                role_name="Global Administrator",
                role_description="Full tenant access.",
                privilege_level="critical",
                principal_id="user-1",
                principal_type="User",
                object_type="user",
                display_name="Ada Guest",
                principal_name="ada.guest@example.com",
                enabled=True,
                user_type="Guest",
                last_successful_utc="2026-04-01T00:00:00Z",
                assignment_type="direct",
                status="critical",
                flags=["Guest user holds a direct Entra directory role."],
            )
        ],
        warnings=["Membership list was truncated to the first 100 results."],
        scope_notes=["This lane reviews direct Microsoft Entra directory-role memberships with live Graph membership lookup per role."],
    )


def test_security_access_review_route_returns_payload_on_azure_host(test_client, monkeypatch):
    import routes_azure_security

    monkeypatch.setattr(routes_azure_security, "build_security_access_review", _response)

    resp = test_client.get(
        "/api/azure/security/access-review",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"][0]["label"] == "Privileged principals"
    assert payload["assignments"][0]["role_name"] == "Owner"


def test_security_access_review_route_is_azure_only(test_client):
    resp = test_client.get("/api/azure/security/access-review")

    assert resp.status_code == 404
    assert "only available on azure.movedocs.com" in resp.json()["detail"]


def test_security_app_hygiene_route_returns_payload_on_azure_host(test_client, monkeypatch):
    import routes_azure_security

    monkeypatch.setattr(routes_azure_security, "build_security_application_hygiene", _app_hygiene_response)

    resp = test_client.get(
        "/api/azure/security/app-hygiene",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"][0]["label"] == "Expired credentials"
    assert payload["flagged_apps"][0]["display_name"] == "Payroll Connector"


def test_security_app_hygiene_route_is_azure_only(test_client):
    resp = test_client.get("/api/azure/security/app-hygiene")

    assert resp.status_code == 404
    assert "only available on azure.movedocs.com" in resp.json()["detail"]


def test_security_break_glass_route_returns_payload_on_azure_host(test_client, monkeypatch):
    import routes_azure_security

    monkeypatch.setattr(routes_azure_security, "build_security_break_glass_validation", _break_glass_response)

    resp = test_client.get(
        "/api/azure/security/break-glass-validation",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"][0]["label"] == "Matched accounts"
    assert payload["accounts"][0]["display_name"] == "Emergency Admin"


def test_security_break_glass_route_is_azure_only(test_client):
    resp = test_client.get("/api/azure/security/break-glass-validation")

    assert resp.status_code == 404
    assert "only available on azure.movedocs.com" in resp.json()["detail"]


def test_security_directory_role_review_route_returns_payload_on_azure_host(test_client, monkeypatch):
    import routes_azure_security

    monkeypatch.setattr(routes_azure_security, "build_security_directory_role_review", _directory_role_review_response)

    resp = test_client.get(
        "/api/azure/security/directory-role-review",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"][0]["label"] == "Roles with direct members"
    assert payload["roles"][0]["display_name"] == "Global Administrator"
    assert payload["memberships"][0]["principal_name"] == "ada.guest@example.com"


def test_security_directory_role_review_route_is_azure_only(test_client):
    resp = test_client.get("/api/azure/security/directory-role-review")

    assert resp.status_code == 404
    assert "only available on azure.movedocs.com" in resp.json()["detail"]
