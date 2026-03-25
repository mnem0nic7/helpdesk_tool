"""Attachment helpers for Jira-backed downloads and in-site previews."""

from __future__ import annotations

import logging
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from config import DATA_DIR
from jira_client import JiraClient
from metrics import parse_dt

logger = logging.getLogger(__name__)

_PREVIEW_CACHE_DIR = Path(DATA_DIR) / "attachment_previews"
_OFFICE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
}
_TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_GENERATED_STEM_RE = re.compile(r"^(?:\d{10,}|[0-9a-f]{24,}|[0-9_-]{14,})$", re.IGNORECASE)
_MAX_OFFICE_PREVIEW_BYTES = 25 * 1024 * 1024
_CONVERSION_TIMEOUT_SECONDS = 90
_CACHE_TTL = timedelta(days=7)
_CLEANUP_INTERVAL_SECONDS = 30 * 60
_last_cleanup_started = 0.0


class AttachmentPreviewError(RuntimeError):
    """Raised when an attachment preview cannot be generated."""


def normalize_attachment_id(value: str | int) -> str:
    return str(value or "").strip()


def extension_for_attachment(filename: str, mime_type: str = "") -> str:
    ext = Path(str(filename or "").strip()).suffix.lower()
    if ext:
        return ext
    guessed = mimetypes.guess_extension(str(mime_type or "").split(";")[0].strip().lower())
    return (guessed or "").lower()


def is_generated_attachment_name(filename: str) -> bool:
    stem = Path(str(filename or "").strip()).stem.strip().lower()
    if not stem:
        return True
    if _GENERATED_STEM_RE.fullmatch(stem):
        return True
    return bool(len(stem) >= 14 and not re.search(r"[a-z]", stem))


def infer_attachment_mime_type(filename: str, mime_type: str = "") -> str:
    normalized = str(mime_type or "").split(";")[0].strip().lower()
    if normalized:
        return normalized
    guessed, _encoding = mimetypes.guess_type(filename or "")
    return str(guessed or "application/octet-stream")


def preview_kind_for_attachment(filename: str, mime_type: str = "") -> str:
    ext = extension_for_attachment(filename, mime_type)
    normalized_mime = infer_attachment_mime_type(filename, mime_type)
    if normalized_mime == "application/pdf" or ext == ".pdf":
        return "pdf"
    if normalized_mime.startswith("image/"):
        return "image"
    if ext in _TEXT_EXTENSIONS or normalized_mime.startswith("text/"):
        return "text"
    if ext in _OFFICE_EXTENSIONS:
        return "office"
    return "unsupported"


def preview_available_for_attachment(filename: str, mime_type: str = "") -> bool:
    return preview_kind_for_attachment(filename, mime_type) != "unsupported"


def fallback_attachment_display_name(
    ticket_key: str,
    *,
    filename: str,
    mime_type: str = "",
    created: str = "",
) -> str:
    ext = extension_for_attachment(filename, mime_type)
    preview_kind = preview_kind_for_attachment(filename, mime_type)
    type_label = {
        "image": "Image",
        "pdf": "PDF",
        "text": "Document",
        "office": "Office Document",
    }.get(preview_kind, "Attachment")
    created_dt = parse_dt(created)
    if created_dt:
        timestamp = created_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H-%M")
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H-%M")
    return f"{ticket_key} - {type_label} - {timestamp}{ext}"


def display_name_for_attachment(
    ticket_key: str,
    *,
    filename: str,
    mime_type: str = "",
    created: str = "",
) -> str:
    raw_filename = str(filename or "").strip()
    if raw_filename and not is_generated_attachment_name(raw_filename):
        return raw_filename
    return fallback_attachment_display_name(
        ticket_key,
        filename=raw_filename,
        mime_type=mime_type,
        created=created,
    )


def serialize_attachment(
    ticket_key: str,
    attachment: dict[str, Any],
) -> dict[str, Any]:
    attachment_id = normalize_attachment_id(attachment.get("id"))
    raw_filename = str(attachment.get("filename") or "").strip()
    mime_type = infer_attachment_mime_type(raw_filename, str(attachment.get("mimeType") or ""))
    preview_kind = preview_kind_for_attachment(raw_filename, mime_type)
    preview_available = preview_available_for_attachment(raw_filename, mime_type)
    display_name = display_name_for_attachment(
        ticket_key,
        filename=raw_filename,
        mime_type=mime_type,
        created=str(attachment.get("created") or ""),
    )
    download_url = (
        f"/api/tickets/{quote(ticket_key, safe='')}/attachments/{quote(attachment_id, safe='')}/download"
        if attachment_id
        else ""
    )
    native_preview_url = (
        f"/api/tickets/{quote(ticket_key, safe='')}/attachments/{quote(attachment_id, safe='')}/preview"
        if attachment_id and preview_kind in {"image", "pdf", "text"}
        else ""
    )
    converted_preview_url = (
        f"/api/tickets/{quote(ticket_key, safe='')}/attachments/{quote(attachment_id, safe='')}/preview-converted"
        if attachment_id and preview_kind == "office"
        else ""
    )
    preview_url = converted_preview_url or native_preview_url
    return {
        "id": attachment_id,
        "filename": raw_filename,
        "raw_filename": raw_filename,
        "display_name": display_name,
        "extension": extension_for_attachment(raw_filename, mime_type),
        "mime_type": mime_type,
        "size": int(attachment.get("size") or 0),
        "created": attachment.get("created", ""),
        "author": ((attachment.get("author") or {}).get("displayName") or ""),
        "content_url": download_url,
        "thumbnail_url": preview_url if preview_kind == "image" else "",
        "download_url": download_url,
        "preview_url": preview_url,
        "converted_preview_url": converted_preview_url,
        "preview_kind": preview_kind,
        "preview_available": preview_available,
    }


def find_attachment(issue: dict[str, Any], attachment_id: str) -> dict[str, Any] | None:
    target_id = normalize_attachment_id(attachment_id)
    for attachment in (issue.get("fields", {}).get("attachment") or []):
        if normalize_attachment_id(attachment.get("id")) == target_id:
            return attachment
    return None


def fetch_attachment_content(client: JiraClient, attachment: dict[str, Any]) -> tuple[bytes, str]:
    content_url = str(attachment.get("content") or "").strip()
    if not content_url:
        raise AttachmentPreviewError("Attachment content URL is missing.")
    response = client.session.get(content_url, timeout=(10, 60))
    client._raise_for_status(response)
    content_type = str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    mime_type = infer_attachment_mime_type(
        str(attachment.get("filename") or ""),
        content_type or str(attachment.get("mimeType") or ""),
    )
    return response.content, mime_type


def build_content_disposition(filename: str, *, inline: bool) -> str:
    safe_filename = str(filename or "attachment").strip() or "attachment"
    encoded = quote(safe_filename)
    mode = "inline" if inline else "attachment"
    return f"{mode}; filename*=UTF-8''{encoded}"


def _preview_cache_key(attachment: dict[str, Any]) -> str:
    attachment_id = normalize_attachment_id(attachment.get("id")) or "attachment"
    size = int(attachment.get("size") or 0)
    created = str(attachment.get("created") or "").strip()
    created_dt = parse_dt(created)
    created_token = (
        created_dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        if created_dt
        else "unknown"
    )
    return f"{attachment_id}-{size}-{created_token}"


def _cleanup_preview_cache() -> None:
    global _last_cleanup_started
    now_ts = time.monotonic()
    if now_ts - _last_cleanup_started < _CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup_started = now_ts
    cache_dir = _PREVIEW_CACHE_DIR
    if not cache_dir.exists():
        return
    cutoff = datetime.now(timezone.utc) - _CACHE_TTL
    try:
        for candidate in cache_dir.glob("*"):
            try:
                modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc)
            except FileNotFoundError:
                continue
            if modified < cutoff:
                if candidate.is_dir():
                    shutil.rmtree(candidate, ignore_errors=True)
                else:
                    candidate.unlink(missing_ok=True)
    except Exception:
        logger.exception("Failed to clean stale attachment preview cache")


def _libreoffice_binary() -> str | None:
    for name in ("libreoffice", "soffice"):
        path = shutil.which(name)
        if path:
            return path
    return None


def ensure_office_preview_pdf(client: JiraClient, attachment: dict[str, Any]) -> Path:
    preview_kind = preview_kind_for_attachment(
        str(attachment.get("filename") or ""),
        str(attachment.get("mimeType") or ""),
    )
    if preview_kind != "office":
        raise AttachmentPreviewError("Attachment does not support Office conversion preview.")
    if int(attachment.get("size") or 0) > _MAX_OFFICE_PREVIEW_BYTES:
        raise AttachmentPreviewError("Attachment is too large for inline Office preview.")
    binary = _libreoffice_binary()
    if not binary:
        raise AttachmentPreviewError("Office preview is not available on this server.")

    _PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_preview_cache()

    cache_path = _PREVIEW_CACHE_DIR / f"{_preview_cache_key(attachment)}.pdf"
    if cache_path.exists():
        return cache_path

    original_blob, _mime_type = fetch_attachment_content(client, attachment)
    original_name = str(attachment.get("filename") or "").strip() or (
        f"attachment{extension_for_attachment('', str(attachment.get('mimeType') or ''))}"
    )
    input_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name) or "attachment"

    with tempfile.TemporaryDirectory(prefix="attachment-preview-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_path = tmpdir_path / input_name
        input_path.write_bytes(original_blob)
        env = dict(os.environ)
        env.setdefault("HOME", tmpdir)
        env.setdefault("TMPDIR", tmpdir)
        env.setdefault("SAL_USE_VCLPLUGIN", "svp")
        command = [
            binary,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            tmpdir,
            str(input_path),
        ]
        started = time.monotonic()
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=_CONVERSION_TIMEOUT_SECONDS,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning("Attachment Office preview timed out for %s", attachment.get("id"))
            raise AttachmentPreviewError("Office preview conversion timed out.") from exc
        duration_ms = int((time.monotonic() - started) * 1000)
        output_path = tmpdir_path / f"{input_path.stem}.pdf"
        if result.returncode != 0 or not output_path.exists():
            logger.warning(
                "Attachment Office preview conversion failed for %s (%sms): %s",
                attachment.get("id"),
                duration_ms,
                (result.stderr or result.stdout or "").strip()[:500],
            )
            raise AttachmentPreviewError("Office preview conversion failed.")
        logger.info(
            "Attachment Office preview conversion completed for %s in %sms",
            attachment.get("id"),
            duration_ms,
        )
        tmp_cache = cache_path.with_suffix(".tmp")
        shutil.copyfile(output_path, tmp_cache)
        os.replace(tmp_cache, cache_path)
    return cache_path
