from __future__ import annotations

import io
import zipfile
from pathlib import Path

from knowledge_base import KnowledgeBaseStore


def _docx_blob(lines: list[str]) -> bytes:
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>"
        for line in lines
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body>"
        "</w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _seed_archive(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "KB-EML-001_Email_or_Outlook.docx",
            _docx_blob(
                [
                    "KB-EML-001",
                    "Email or Outlook",
                    "Description",
                    "Covers Outlook, mail flow, and shared mailbox troubleshooting.",
                    "Common Issues",
                    "Mail is not sending.",
                    "Resolution Steps:",
                    "Restart Outlook and verify Exchange connectivity.",
                ]
            ),
        )
    return path


def test_import_seed_archive_extracts_docx_articles(tmp_path):
    archive_path = _seed_archive(tmp_path / "kb.zip")
    store = KnowledgeBaseStore(str(tmp_path / "kb.db"))

    imported = store.import_seed_archive(archive_path)

    assert imported == 1
    articles = store.list_articles()
    assert len(articles) == 1
    article = articles[0]
    assert article.code == "KB-EML-001"
    assert article.request_type == "Email or Outlook"
    assert article.title == "Email or Outlook"
    assert article.summary == "Covers Outlook, mail flow, and shared mailbox troubleshooting."
    assert "Resolution Steps:" in article.content
    assert article.imported_from_seed is True
