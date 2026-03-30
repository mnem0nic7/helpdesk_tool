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
