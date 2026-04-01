from pathlib import Path


def test_sync_users_uses_plain_exchange_access_token() -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "syncUsers" / "syncUsers.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert "Connect-ExchangeOnline -AccessToken $exoToken -Organization $organizationDomain -ShowBanner:$false" in script
    assert "ConvertTo-SecureString $exoToken -AsPlainText -Force" not in script


def test_sync_users_supports_certificate_file_noninteractive_auth() -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "syncUsers" / "syncUsers.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert '$certificatePath = if ($customerData.certificatePath)' in script
    assert '$certificatePassword = if ($customerData.certificatePassword)' in script
    assert "$hasCertificateFileAuth = ($certificatePath) -AND ($certificatePassword)" in script
    assert "Connect-MgGraph -TenantId $tenantId -ApplicationId $appId -Certificate $graphCertificate -NoWelcome" in script
    assert (
        "Connect-ExchangeOnline -CertificateFilePath $certificatePath -CertificatePassword $secureCertificatePassword -AppId $appId -Organization $organizationDomain -ShowBanner:$false"
        in script
    )


def test_sync_users_keeps_device_code_graph_app_id_outside_noninteractive_gate() -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "syncUsers" / "syncUsers.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert (
        "if (($tenantId) -AND ($appId) -AND ($organizationDomain) -AND ($hasCertificateFileAuth -OR $hasCertificateThumbprintAuth -OR $hasClientSecretAuth)) {"
        in script
    )
    assert 'if (-not $mgGraphAppId -or -not $deviceCodeUrl -or -not $tokenUrl -or -not $deviceLoginUrl) {' in script
