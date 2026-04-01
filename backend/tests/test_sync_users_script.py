from pathlib import Path


def test_sync_users_uses_plain_exchange_access_token() -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "syncUsers" / "syncUsers.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert "Connect-ExchangeOnline -AccessToken $exoToken -Organization $organizationDomain -ShowBanner:$false" in script
    assert "ConvertTo-SecureString $exoToken -AsPlainText -Force" not in script
