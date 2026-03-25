from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import attachment_service


def test_serialize_attachment_preserves_meaningful_name():
    payload = attachment_service.serialize_attachment(
        "OIT-123",
        {
            "id": "9001",
            "filename": "vpn-troubleshooting.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "size": 2048,
            "created": "2026-03-01T09:00:00+00:00",
            "author": {"displayName": "Alice Admin"},
        },
    )

    assert payload["filename"] == "vpn-troubleshooting.docx"
    assert payload["raw_filename"] == "vpn-troubleshooting.docx"
    assert payload["display_name"] == "vpn-troubleshooting.docx"
    assert payload["preview_kind"] == "office"
    assert payload["preview_available"] is True
    assert payload["download_url"].endswith("/api/tickets/OIT-123/attachments/9001/download")


def test_serialize_attachment_aliases_generated_numeric_name():
    payload = attachment_service.serialize_attachment(
        "OIT-123",
        {
            "id": "9002",
            "filename": "10875238511763560924.xls",
            "mimeType": "application/vnd.ms-excel",
            "size": 65536,
            "created": "2026-03-01T09:00:00+00:00",
            "author": {"displayName": "Alice Admin"},
        },
    )

    assert payload["raw_filename"] == "10875238511763560924.xls"
    assert payload["display_name"] == "OIT-123 - Office Document - 2026-03-01 09-00.xls"
    assert payload["preview_kind"] == "office"
    assert payload["preview_url"].endswith("/preview-converted")
    assert payload["converted_preview_url"].endswith("/preview-converted")


def test_serialize_attachment_treats_generic_png_mimetype_as_image_preview():
    payload = attachment_service.serialize_attachment(
        "OIT-19355",
        {
            "id": "9011",
            "filename": "1609241234567.png",
            "mimeType": "application-type",
            "size": 10240,
            "created": "2026-03-25T17:53:18+00:00",
            "author": {"displayName": "OSIJIRAOCC"},
        },
    )

    assert payload["mime_type"] == "image/png"
    assert payload["preview_kind"] == "image"
    assert payload["preview_available"] is True
    assert payload["thumbnail_url"].endswith("/api/tickets/OIT-19355/attachments/9011/preview")


def test_serialize_attachment_aliases_long_machine_upload_name():
    payload = attachment_service.serialize_attachment(
        "OIT-19355",
        {
            "id": "9010",
            "filename": "-osiocc_occv2_site_occ.osidigital.com_uploads_etr_attachments_9260297081774461152.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "size": 20480,
            "created": "2026-03-25T17:53:21+00:00",
            "author": {"displayName": "Alice Admin"},
        },
    )

    assert payload["raw_filename"].startswith("-osiocc_occv2_site_occ.osidigital.com_uploads")
    assert payload["display_name"] == "OIT-19355 - Office Document - 2026-03-25 17-53.xlsx"
    assert payload["preview_kind"] == "office"


def test_ensure_office_preview_pdf_uses_cache(tmp_path, monkeypatch):
    attachment = {
        "id": "9003",
        "filename": "10875238511763560924.xlsx",
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "size": 1024,
        "created": "2026-03-01T09:00:00+00:00",
    }
    run_calls: list[list[str]] = []

    monkeypatch.setattr(attachment_service, "_PREVIEW_CACHE_DIR", tmp_path)
    monkeypatch.setattr(attachment_service, "_cleanup_preview_cache", lambda: None)
    monkeypatch.setattr(attachment_service, "_libreoffice_binary", lambda: "/usr/bin/libreoffice")
    monkeypatch.setattr(
        attachment_service,
        "fetch_attachment_content",
        lambda client, att: (b"fake-office-content", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )

    def _fake_run(command, capture_output, text, timeout, check, env):
        run_calls.append(command)
        input_path = Path(command[-1])
        output_path = input_path.with_suffix(".pdf")
        output_path.write_bytes(b"%PDF-1.4\nconverted")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(attachment_service.subprocess, "run", _fake_run)

    first_path = attachment_service.ensure_office_preview_pdf(SimpleNamespace(), attachment)
    second_path = attachment_service.ensure_office_preview_pdf(SimpleNamespace(), attachment)

    assert first_path.exists()
    assert second_path == first_path
    assert first_path.read_bytes().startswith(b"%PDF-1.4")
    assert len(run_calls) == 1
