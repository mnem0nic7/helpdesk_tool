"""send_email attachment payload shape."""
import base64

import email_service


def _install_fakes(monkeypatch):
    monkeypatch.setattr(email_service, "ENTRA_TENANT_ID", "t")
    monkeypatch.setattr(email_service, "ENTRA_CLIENT_ID", "c")
    monkeypatch.setattr(email_service, "ENTRA_CLIENT_SECRET", "s")

    async def fake_token():
        return "tok"

    monkeypatch.setattr(email_service, "_get_access_token", fake_token)
    captured = {}

    class FakeResp:
        status_code = 202
        text = ""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            captured["json"] = json
            return FakeResp()

    monkeypatch.setattr(email_service.httpx, "AsyncClient", lambda: FakeClient())
    return captured


async def test_send_email_includes_file_attachments(monkeypatch):
    captured = _install_fakes(monkeypatch)
    ok = await email_service.send_email(
        ["a@example.com"],
        "subj",
        "<p>hi</p>",
        attachments=[{"name": "r.xlsx", "content_type": "application/vnd.ms-excel", "content": b"abc"}],
    )
    assert ok is True
    att = captured["json"]["message"]["attachments"][0]
    assert att["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert att["name"] == "r.xlsx"
    assert att["contentType"] == "application/vnd.ms-excel"
    assert att["contentBytes"] == base64.b64encode(b"abc").decode()


async def test_send_email_without_attachments_has_no_attachments_key(monkeypatch):
    captured = _install_fakes(monkeypatch)
    assert await email_service.send_email(["a@example.com"], "s", "<p>x</p>") is True
    assert "attachments" not in captured["json"]["message"]
