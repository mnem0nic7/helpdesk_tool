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
    SecurityConditionalAccessChange,
    SecurityConditionalAccessPolicy,
    SecurityConditionalAccessTrackerResponse,
    SecurityDeviceActionJob,
    SecurityDeviceActionJobResult,
    SecurityDeviceComplianceDevice,
    SecurityDeviceComplianceResponse,
    SecurityDirectoryRoleReviewMembership,
    SecurityDirectoryRoleReviewResponse,
    SecurityDirectoryRoleReviewRole,
    UserAdminReference,
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


def _conditional_access_tracker_response(_session=None) -> SecurityConditionalAccessTrackerResponse:
    return SecurityConditionalAccessTrackerResponse(
        generated_at="2026-04-03T03:00:00Z",
        conditional_access_last_refresh="2026-04-03T02:45:00Z",
        access_available=True,
        access_message="Conditional Access policy drift review is available.",
        metrics=[
            SecurityAccessReviewMetric(
                key="tracked_policies",
                label="Tracked policies",
                value=2,
                detail="Two policies are cached.",
                tone="sky",
            )
        ],
        policies=[
            SecurityConditionalAccessPolicy(
                policy_id="policy-1",
                display_name="Require MFA for admins",
                state="enabled",
                created_date_time="2026-01-01T00:00:00Z",
                modified_date_time="2026-04-03T01:00:00Z",
                user_scope_summary="2 role target(s) - 1 exception(s)",
                application_scope_summary="All cloud apps",
                grant_controls=["Mfa"],
                session_controls=[],
                impact_level="warning",
                risk_tags=["role_targeted", "exception_surface"],
            )
        ],
        changes=[
            SecurityConditionalAccessChange(
                event_id="event-1",
                activity_date_time="2026-04-03T02:15:00Z",
                activity_display_name="Update conditional access policy",
                result="success",
                initiated_by_display_name="Ada Lovelace",
                initiated_by_principal_name="ada@example.com",
                initiated_by_type="user",
                target_policy_id="policy-1",
                target_policy_name="Require MFA for admins",
                impact_level="warning",
                change_summary="Update conditional access policy for Require MFA for admins by Ada Lovelace",
                modified_properties=["grantControls"],
                flags=["Change touched policy scope or enforcement controls."],
            )
        ],
        warnings=[],
        scope_notes=["This lane tracks cached Microsoft Entra Conditional Access policies."],
    )


def _device_compliance_response(_session=None) -> SecurityDeviceComplianceResponse:
    return SecurityDeviceComplianceResponse(
        generated_at="2026-04-03T02:00:00Z",
        device_last_refresh="2026-04-03T01:56:00Z",
        access_available=True,
        access_message="Tenant-wide device compliance review is available.",
        metrics=[
            SecurityAccessReviewMetric(
                key="managed_devices",
                label="Managed devices",
                value=2,
                detail="Two devices are cached.",
                tone="sky",
            )
        ],
        devices=[
            SecurityDeviceComplianceDevice(
                id="device-1",
                device_name="Payroll Laptop",
                operating_system="Windows",
                operating_system_version="11",
                compliance_state="noncompliant",
                management_state="managed",
                owner_type="company",
                enrollment_type="windowsAzureADJoin",
                last_sync_date_time="2026-04-03T01:00:00Z",
                last_sync_age_days=0,
                azure_ad_device_id="aad-1",
                primary_users=[
                    UserAdminReference(
                        id="user-1",
                        display_name="Ada Lovelace",
                        principal_name="ada@example.com",
                        mail="ada@example.com",
                    )
                ],
                risk_level="critical",
                finding_tags=["noncompliant_or_grace"],
                recommended_actions=["Run an Intune device sync and review the failing compliance policies."],
                action_ready=True,
                supported_actions=["device_sync", "device_remote_lock", "device_retire", "device_wipe"],
                action_blockers=[],
            )
        ],
        warnings=[],
        scope_notes=["This lane reviews cached Intune managed-device posture across the tenant."],
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


def test_security_conditional_access_tracker_route_returns_payload_on_azure_host(test_client, monkeypatch):
    import routes_azure_security

    monkeypatch.setattr(routes_azure_security, "build_security_conditional_access_tracker", _conditional_access_tracker_response)

    resp = test_client.get(
        "/api/azure/security/conditional-access-tracker",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"][0]["label"] == "Tracked policies"
    assert payload["policies"][0]["display_name"] == "Require MFA for admins"
    assert payload["changes"][0]["target_policy_name"] == "Require MFA for admins"


def test_security_conditional_access_tracker_route_is_azure_only(test_client):
    resp = test_client.get("/api/azure/security/conditional-access-tracker")

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


def test_security_device_compliance_route_returns_payload_on_azure_host(test_client, monkeypatch):
    import routes_azure_security

    monkeypatch.setattr(routes_azure_security, "build_security_device_compliance_review", _device_compliance_response)

    resp = test_client.get(
        "/api/azure/security/device-compliance",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metrics"][0]["label"] == "Managed devices"
    assert payload["devices"][0]["device_name"] == "Payroll Laptop"


def test_security_device_action_routes_queue_and_return_results(test_client, monkeypatch):
    import routes_azure_security

    monkeypatch.setattr(
        routes_azure_security.security_device_jobs,
        "create_job",
        lambda **_: SecurityDeviceActionJob(
            job_id="job-1",
            status="queued",
            action_type="device_sync",
            device_ids=["device-1"],
            device_names=["Payroll Laptop"],
            requested_by_email="test@example.com",
            requested_by_name="Test User",
            requested_at="2026-04-03T02:00:00Z",
            progress_total=1,
            progress_message="Queued",
        ).model_dump(),
    )
    monkeypatch.setattr(
        routes_azure_security.security_device_jobs,
        "get_job",
        lambda job_id: SecurityDeviceActionJob(
            job_id=job_id,
            status="completed",
            action_type="device_sync",
            device_ids=["device-1"],
            device_names=["Payroll Laptop"],
            requested_by_email="test@example.com",
            requested_by_name="Test User",
            requested_at="2026-04-03T02:00:00Z",
            completed_at="2026-04-03T02:01:00Z",
            progress_current=1,
            progress_total=1,
            progress_message="Completed",
            success_count=1,
            results_ready=True,
        ).model_dump(),
    )
    monkeypatch.setattr(
        routes_azure_security.security_device_jobs,
        "get_job_results",
        lambda job_id: [
            SecurityDeviceActionJobResult(
                device_id="device-1",
                device_name="Payroll Laptop",
                azure_ad_device_id="aad-1",
                success=True,
                summary=f"Completed {job_id}",
                before_summary={"device_ids": ["device-1"]},
                after_summary={"action": "device_sync"},
            ).model_dump()
        ],
    )

    create_resp = test_client.post(
        "/api/azure/security/device-compliance/actions",
        headers={"host": "azure.movedocs.com"},
        json={
            "action_type": "device_sync",
            "device_ids": ["device-1"],
            "reason": "Compliance drift",
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["job_id"] == "job-1"

    status_resp = test_client.get(
        "/api/azure/security/device-compliance/jobs/job-1",
        headers={"host": "azure.movedocs.com"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"

    results_resp = test_client.get(
        "/api/azure/security/device-compliance/jobs/job-1/results",
        headers={"host": "azure.movedocs.com"},
    )
    assert results_resp.status_code == 200
    assert results_resp.json()[0]["device_name"] == "Payroll Laptop"


def test_security_device_action_routes_require_manage_users(test_client):
    from auth import create_session

    sid = create_session(
        "viewer@example.com",
        "Viewer User",
        auth_provider="atlassian",
        can_manage_users=False,
        is_admin=False,
        site_scope="azure",
    )
    test_client.cookies.set("session_id", sid)

    resp = test_client.post(
        "/api/azure/security/device-compliance/actions",
        headers={"host": "azure.movedocs.com"},
        json={"action_type": "device_sync", "device_ids": ["device-1"]},
    )

    assert resp.status_code == 403
    assert "required" in resp.json()["detail"].lower()
