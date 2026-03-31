from azure_client import AzureApiError
from user_admin_providers import MailboxAdminProvider


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


def test_list_mailbox_delegates_returns_send_on_behalf_entries():
    client = FakeMailboxDelegatesClient()
    provider = MailboxAdminProvider(client=client)

    result = provider.list_mailbox_delegates("shared@example.com")

    assert result["display_name"] == "Shared Mailbox"
    assert result["delegate_count"] == 2
    assert result["delegates"] == [
        {
            "display_name": "Delegate Two",
            "principal_name": "delegate-two@example.com",
            "mail": "delegate-two@example.com",
        },
        {
            "display_name": "Delegate User",
            "principal_name": "delegate@example.com",
            "mail": "delegate@example.com",
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


def test_list_delegate_mailboxes_for_user_filters_orgwide_mailbox_scan():
    client = FakeDelegateMailboxScanClient()
    provider = MailboxAdminProvider(client=client)

    result = provider.list_delegate_mailboxes_for_user("delegate@example.com")

    assert result["display_name"] == "Delegate User"
    assert result["mailbox_count"] == 1
    assert result["scanned_mailbox_count"] == 2
    assert result["mailboxes"] == [
        {
            "display_name": "Shared Mailbox",
            "principal_name": "shared@example.com",
            "primary_address": "shared@example.com",
        }
    ]
