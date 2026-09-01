from azure_client import AzureApiError
from user_admin_providers import EntraAdminProvider, MailboxAdminProvider, UserAdminProviderError


class FakeMailboxRulesClient:
    configured = True

    def __init__(self, *, fail_folder_lookup: bool = False) -> None:
        self.fail_folder_lookup = fail_folder_lookup
        self.batch_payloads: list[list[dict[str, str]]] = []

    def graph_request(self, method: str, path: str, **kwargs):
        assert method == "GET"
        assert path == "users/ada@example.com"
        assert kwargs["params"] == {"$select": "id,displayName,mail,userPrincipalName"}
        return {
            "id": "user-1",
            "displayName": "Ada Lovelace",
            "mail": "ada@example.com",
            "userPrincipalName": "ada@example.com",
        }

    def graph_paged_get(self, path: str, **kwargs):
        assert path == "users/user-1/mailFolders/inbox/messageRules"
        assert kwargs["params"] == {"$top": "999"}
        return [
            {
                "id": "rule-1",
                "displayName": "Move GitHub alerts",
                "sequence": 1,
                "isEnabled": True,
                "hasError": False,
                "actions": {
                    "moveToFolder": "folder-1",
                    "stopProcessingRules": True,
                },
                "conditions": {
                    "fromAddresses": [
                        {
                            "emailAddress": {
                                "address": "alerts@github.com",
                            }
                        }
                    ]
                },
                "exceptions": {},
            }
        ]

    def graph_batch_request(self, requests_payload: list[dict[str, str]]):
        self.batch_payloads.append(requests_payload)
        if self.fail_folder_lookup:
            raise AzureApiError("folder lookup denied", status_code=403)
        return {
            "responses": [
                {
                    "id": "0",
                    "status": 200,
                    "body": {
                        "id": "folder-1",
                        "displayName": "GitHub",
                    },
                }
            ]
        }


def test_list_mailbox_rules_resolves_move_to_folder_names():
    client = FakeMailboxRulesClient()
    provider = MailboxAdminProvider(client=client)

    result = provider.list_mailbox_rules("ada@example.com")

    assert result["display_name"] == "Ada Lovelace"
    assert result["rules"][0]["actions_summary"] == [
        "Move To Folder: GitHub",
        "Stop processing more rules",
    ]
    assert client.batch_payloads == [
        [
            {
                "id": "0",
                "method": "GET",
                "url": "/users/user-1/mailFolders/folder-1?$select=id,displayName,parentFolderId",
            }
        ]
    ]


def test_list_mailbox_rules_falls_back_to_raw_folder_ids_when_lookup_fails():
    client = FakeMailboxRulesClient(fail_folder_lookup=True)
    provider = MailboxAdminProvider(client=client)

    result = provider.list_mailbox_rules("ada@example.com")

    assert result["rules"][0]["actions_summary"] == [
        "Move To Folder: folder-1",
        "Stop processing more rules",
    ]


class FakeMailboxDelegatesClient:
    configured = True

    def __init__(self) -> None:
        self.exchange_calls: list[dict[str, object]] = []

    def exchange_admin_request(
        self,
        endpoint: str,
        *,
        anchor_mailbox: str,
        cmdlet_name: str,
        parameters: dict[str, object] | None = None,
        select: list[str] | None = None,
        next_link: str | None = None,
    ):
        self.exchange_calls.append(
            {
                "endpoint": endpoint,
                "anchor_mailbox": anchor_mailbox,
                "cmdlet_name": cmdlet_name,
                "parameters": parameters,
                "select": select,
                "next_link": next_link,
            }
        )
        return {
            "value": [
                {
                    "DisplayName": "Shared Mailbox",
                    "UserPrincipalName": "shared@example.com",
                    "PrimarySmtpAddress": "shared@example.com",
                    "GrantSendOnBehalfTo": [
                        "delegate@example.com",
                        "delegate-two@example.com",
                    ],
                    "GrantSendOnBehalfToWithDisplayNames": [
                        "Delegate User",
                        "Delegate Two <delegate-two@example.com>",
                    ],
                }
            ]
        }


class FakeExchangePowerShellMailboxDelegates:
    def get_mailbox_delegate_permissions(self, mailbox_identifier: str, *, cancel_requested=None):
        assert cancel_requested is None
        assert mailbox_identifier == "shared@example.com"
        return {
            "send_as": [
                {
                    "Trustee": "Delegate Two <delegate-two@example.com>",
                },
                {
                    "Trustee": "sendas@example.com",
                },
            ],
            "full_access": [
                {
                    "User": "Delegate User",
                },
                {
                    "User": "fullaccess@example.com",
                },
            ],
        }


class FakeDelegateMailboxScanClient:
    configured = True

    def graph_request(self, method: str, path: str, **kwargs):
        assert method == "GET"
        assert path == "users/delegate%40example.com"
        assert kwargs["params"] == {"$select": "displayName,userPrincipalName,mail"}
        return {
            "displayName": "Delegate User",
            "userPrincipalName": "delegate@example.com",
            "mail": "delegate@example.com",
        }

    def exchange_admin_paged_request(
        self,
        endpoint: str,
        *,
        anchor_mailbox: str,
        cmdlet_name: str,
        parameters: dict[str, object] | None = None,
        select: list[str] | None = None,
    ):
        assert endpoint == "Mailbox"
        assert anchor_mailbox == "delegate@example.com"
        assert cmdlet_name == "Get-Mailbox"
        assert parameters == {"ResultSize": 500}
        assert select == [
            "DisplayName",
            "UserPrincipalName",
            "PrimarySmtpAddress",
            "GrantSendOnBehalfTo",
        ]
        return [
            {
                "DisplayName": "Shared Mailbox",
                "UserPrincipalName": "shared@example.com",
                "PrimarySmtpAddress": "shared@example.com",
                "GrantSendOnBehalfTo": ["delegate@example.com"],
            },
            {
                "DisplayName": "Another Mailbox",
                "UserPrincipalName": "another@example.com",
                "PrimarySmtpAddress": "another@example.com",
                "GrantSendOnBehalfTo": ["someoneelse@example.com"],
            },
        ]


class FakeExchangePowerShellUserMatches:
    def get_send_as_mailboxes_for_user(self, user_identifier: str, *, cancel_requested=None):
        assert cancel_requested is None
        assert user_identifier == "delegate@example.com"
        return {
            "mailboxes": [
                {
                    "Identity": "shared@example.com",
                    "DisplayName": "Shared Mailbox",
                    "UserPrincipalName": "shared@example.com",
                    "PrimarySmtpAddress": "shared@example.com",
                    "PermissionTypes": ["send_as"],
                },
                {
                    "Identity": "finance@example.com",
                    "DisplayName": "Finance Mailbox",
                    "UserPrincipalName": "finance@example.com",
                    "PrimarySmtpAddress": "finance@example.com",
                    "PermissionTypes": ["send_as"],
                },
            ],
        }

    def get_full_access_mailboxes_for_user(self, user_identifier: str, *, cancel_requested=None):
        assert cancel_requested is None
        assert user_identifier == "delegate@example.com"
        return {
            "mailbox_count_scanned": 7,
            "mailboxes": [
                {
                    "Identity": "shared@example.com",
                    "DisplayName": "Shared Mailbox",
                    "UserPrincipalName": "shared@example.com",
                    "PrimarySmtpAddress": "shared@example.com",
                    "PermissionTypes": ["full_access"],
                },
            ],
        }


class FakeExchangePowerShellUserMatchesWithFullAccessTimeout(FakeExchangePowerShellUserMatches):
    def get_full_access_mailboxes_for_user(self, user_identifier: str, *, cancel_requested=None):
        assert cancel_requested is None
        assert user_identifier == "delegate@example.com"
        from exchange_online_client import ExchangeOnlinePowerShellError

        raise ExchangeOnlinePowerShellError("Exchange Online PowerShell timed out after 600 seconds.")


def test_list_mailbox_delegates_returns_all_supported_delegate_types():
    client = FakeMailboxDelegatesClient()
    provider = MailboxAdminProvider(
        client=client,
        exchange_powershell=FakeExchangePowerShellMailboxDelegates(),
    )

    result = provider.list_mailbox_delegates("shared@example.com")

    assert result["display_name"] == "Shared Mailbox"
    assert result["delegate_count"] == 5
    assert result["permission_counts"] == {
        "send_on_behalf": 2,
        "send_as": 2,
        "full_access": 2,
    }
    assert result["delegates"] == [
        {
            "identity": "delegate-two@example.com",
            "display_name": "Delegate Two",
            "principal_name": "delegate-two@example.com",
            "mail": "delegate-two@example.com",
            "permission_types": ["send_on_behalf", "send_as"],
        },
        {
            "identity": "Delegate User",
            "display_name": "Delegate User",
            "principal_name": "",
            "mail": "",
            "permission_types": ["full_access"],
        },
        {
            "identity": "delegate@example.com",
            "display_name": "Delegate User",
            "principal_name": "delegate@example.com",
            "mail": "delegate@example.com",
            "permission_types": ["send_on_behalf"],
        },
        {
            "identity": "fullaccess@example.com",
            "display_name": "",
            "principal_name": "fullaccess@example.com",
            "mail": "fullaccess@example.com",
            "permission_types": ["full_access"],
        },
        {
            "identity": "sendas@example.com",
            "display_name": "",
            "principal_name": "sendas@example.com",
            "mail": "sendas@example.com",
            "permission_types": ["send_as"],
        },
    ]
    assert client.exchange_calls == [
        {
            "endpoint": "Mailbox",
            "anchor_mailbox": "shared@example.com",
            "cmdlet_name": "Get-Mailbox",
            "parameters": {
                "Identity": "shared@example.com",
                "IncludeGrantSendOnBehalfToWithDisplayNames": True,
            },
            "select": [
                "DisplayName",
                "UserPrincipalName",
                "PrimarySmtpAddress",
                "GrantSendOnBehalfTo",
                "GrantSendOnBehalfToWithDisplayNames",
            ],
            "next_link": None,
        }
    ]


def test_list_delegate_mailboxes_for_user_merges_send_on_behalf_send_as_and_full_access():
    client = FakeDelegateMailboxScanClient()
    provider = MailboxAdminProvider(
        client=client,
        exchange_powershell=FakeExchangePowerShellUserMatches(),
    )

    result = provider.list_delegate_mailboxes_for_user("delegate@example.com")

    assert result["display_name"] == "Delegate User"
    assert result["mailbox_count"] == 2
    assert result["scanned_mailbox_count"] == 7
    assert result["permission_counts"] == {
        "send_on_behalf": 1,
        "send_as": 2,
        "full_access": 1,
    }
    assert result["mailboxes"] == [
        {
            "identity": "finance@example.com",
            "display_name": "Finance Mailbox",
            "principal_name": "finance@example.com",
            "primary_address": "finance@example.com",
            "permission_types": ["send_as"],
        },
        {
            "identity": "shared@example.com",
            "display_name": "Shared Mailbox",
            "principal_name": "shared@example.com",
            "primary_address": "shared@example.com",
            "permission_types": ["send_on_behalf", "send_as", "full_access"],
        }
    ]


def test_list_delegate_mailboxes_for_user_returns_partial_results_when_full_access_scan_times_out():
    client = FakeDelegateMailboxScanClient()
    provider = MailboxAdminProvider(
        client=client,
        exchange_powershell=FakeExchangePowerShellUserMatchesWithFullAccessTimeout(),
    )

    result = provider.list_delegate_mailboxes_for_user("delegate@example.com")

    assert result["mailbox_count"] == 2
    assert result["permission_counts"] == {
        "send_on_behalf": 1,
        "send_as": 2,
        "full_access": 0,
    }
    assert "Full Access matches are not fully included" in result["note"]


# ---------------------------------------------------------------------------
# EntraAdminProvider.validate_cloud_group_removal
# ---------------------------------------------------------------------------

class FakeEntraClientForResetPassword:
    configured = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def graph_request(self, method: str, path: str, **kwargs):
        self.calls.append({"method": method, "path": path, "json_body": kwargs.get("json_body")})
        return {}


def test_reset_password_patches_user_password_profile_directly():
    client = FakeEntraClientForResetPassword()
    provider = EntraAdminProvider(client=client)

    result = provider.execute("reset_password", "user-1", {"force_change_on_next_login": True})

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["method"] == "PATCH"
    assert call["path"] == "users/user-1"
    assert call["json_body"]["passwordProfile"]["forceChangePasswordNextSignIn"] is True
    assert call["json_body"]["passwordProfile"]["password"] == result["one_time_secret"]


def test_reset_password_uses_requested_password_when_provided():
    client = FakeEntraClientForResetPassword()
    provider = EntraAdminProvider(client=client)

    result = provider.execute(
        "reset_password", "user-1", {"new_password": "Sup3r!Secret1", "force_change_on_next_login": False}
    )

    call = client.calls[0]
    assert call["json_body"]["passwordProfile"]["password"] == "Sup3r!Secret1"
    assert call["json_body"]["passwordProfile"]["forceChangePasswordNextSignIn"] is False
    assert result["one_time_secret"] == "Sup3r!Secret1"


class FakeEntraClientForGroupCleanup:
    configured = True

    def __init__(self, member_of: list[dict], group_details: dict[str, dict], delete_should_fail: set[str] | None = None) -> None:
        self._member_of = member_of
        self._group_details = group_details
        self.delete_calls: list[str] = []
        self.delete_should_fail = delete_should_fail or set()

    def graph_paged_get(self, path: str, **kwargs):
        return self._member_of

    def graph_request(self, method: str, path: str, **kwargs):
        group_id = path.split("/")[1]
        if method == "GET":
            return self._group_details[group_id]
        if method == "DELETE":
            self.delete_calls.append(group_id)
            if group_id in self.delete_should_fail:
                raise AzureApiError("Graph rejected removal", status_code=400)
            return {}
        raise AssertionError(f"unexpected call {method} {path}")


def test_remove_direct_cloud_group_memberships_routes_distribution_lists_separately():
    member_of = [
        {"@odata.type": "#microsoft.graph.group", "id": "g-sec", "displayName": "Security Group"},
        {"@odata.type": "#microsoft.graph.group", "id": "g-dl", "displayName": "All Staff"},
    ]
    group_details = {
        "g-sec": {
            "id": "g-sec",
            "displayName": "Security Group",
            "groupTypes": [],
            "mailEnabled": False,
            "securityEnabled": True,
            "onPremisesSyncEnabled": False,
        },
        "g-dl": {
            "id": "g-dl",
            "displayName": "All Staff",
            "mail": "allstaff@example.com",
            "groupTypes": [],
            "mailEnabled": True,
            "securityEnabled": False,
            "onPremisesSyncEnabled": False,
        },
    }
    client = FakeEntraClientForGroupCleanup(member_of, group_details)
    provider = EntraAdminProvider(client=client)

    result = provider.remove_direct_cloud_group_memberships("user-1")

    # Graph DELETE is only attempted for the security group — the distribution
    # list is never sent through /members/$ref since Graph rejects it outright.
    assert client.delete_calls == ["g-sec"]
    assert result["after_summary"]["removed_groups"] == ["Security Group"]
    assert result["after_summary"]["distribution_lists"] == [
        {"id": "g-dl", "name": "All Staff", "mail": "allstaff@example.com"}
    ]


class FakeEntraClientForValidation:
    configured = True

    def __init__(self, groups: list[dict]) -> None:
        self._groups = groups

    def graph_paged_get(self, path: str, **kwargs):
        return self._groups


def test_validate_cloud_group_removal_returns_ok_when_all_groups_gone():
    groups_after = []  # user has no groups left
    client = FakeEntraClientForValidation(groups_after)
    provider = EntraAdminProvider(client=client)

    result = provider.validate_cloud_group_removal(
        "user-1",
        expected_removed=["GroupA", "GroupB"],
    )

    assert result["ok"] is True
    assert result["still_present_count"] == 0
    assert result["remaining_groups"] == []


def test_validate_cloud_group_removal_detects_still_present_group():
    groups_after = [
        {"@odata.type": "#microsoft.graph.group", "displayName": "GroupA", "id": "g1"},
    ]
    client = FakeEntraClientForValidation(groups_after)
    provider = EntraAdminProvider(client=client)

    result = provider.validate_cloud_group_removal(
        "user-1",
        expected_removed=["GroupA", "GroupB"],
    )

    assert result["ok"] is False
    assert result["still_present_count"] == 1
    assert "GroupA" in result["remaining_groups"]


def test_validate_cloud_group_removal_ignores_directory_roles():
    groups_after = [
        {"@odata.type": "#microsoft.graph.directoryRole", "displayName": "GroupA", "id": "r1"},
    ]
    client = FakeEntraClientForValidation(groups_after)
    provider = EntraAdminProvider(client=client)

    result = provider.validate_cloud_group_removal(
        "user-1",
        expected_removed=["GroupA"],
    )

    # directoryRole objects should be filtered out
    assert result["ok"] is True
    assert result["still_present_count"] == 0


def test_validate_cloud_group_removal_fast_path_for_empty_expected():
    client = FakeEntraClientForValidation([])
    provider = EntraAdminProvider(client=client)

    result = provider.validate_cloud_group_removal("user-1", expected_removed=[])

    assert result["ok"] is True
    assert result["still_present_count"] == 0


def test_validate_cloud_group_removal_returns_error_dict_on_api_failure():
    from azure_client import AzureApiError

    class FailingClient:
        configured = True

        def graph_paged_get(self, path: str, **kwargs):
            raise AzureApiError("Graph API unavailable", status_code=503)

    provider = EntraAdminProvider(client=FailingClient())

    result = provider.validate_cloud_group_removal("user-1", expected_removed=["GroupA"])

    assert result["ok"] is False
    # still_present_count should be -1 to signal a lookup failure
    assert result.get("still_present_count") == -1 or "error" in result
