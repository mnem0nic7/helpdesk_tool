"""SQLite-backed internal knowledge base with seed import from DOCX articles."""

from __future__ import annotations

import io
import logging
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR
from models import KnowledgeBaseArticle, KnowledgeBaseArticleUpsertRequest

logger = logging.getLogger(__name__)

_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_REQUEST_TYPE_BY_CODE = {
    "KB-APP-001": "Business Application Support",
    "KB-EML-001": "Email or Outlook",
    "KB-GEN-001": "Get IT help",
    "KB-HW-001": "Report a computer equipment problem",
    "KB-OFF-001": "Offboard employees",
    "KB-ONB-001": "Onboard new employees",
    "KB-PHN-001": "Phone RingCentral",
    "KB-PWD-001": "Password MFA Authentication",
    "KB-SEC-001": "Security Alert",
    "KB-SRV-001": "Server Infrastructure Database",
    "KB-STR-001": "Backup and Storage",
    "KB-SW-001": "Request new PC software",
    "KB-VDI-001": "Virtual Desktop",
    "KB-VPN-001": "VPN",
}
_STOP_WORDS = {
    "about", "after", "again", "all", "also", "and", "are", "can", "for", "from", "has",
    "have", "how", "into", "its", "may", "new", "not", "off", "one", "our", "that", "the",
    "their", "them", "then", "there", "these", "this", "use", "used", "user", "when", "with",
    "your",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "article"


def _tokenize(text: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]{3,}", text.lower())
        if token not in _STOP_WORDS
    }
    return tokens


def _table_first_cell_text(tbl: ET.Element) -> str:
    first_cell = tbl.find(".//w:tc", _DOCX_NS)
    if first_cell is None:
        return ""
    first_para = first_cell.find(".//w:p", _DOCX_NS)
    if first_para is None:
        return ""
    return "".join((n.text or "") for n in first_para.findall(".//w:t", _DOCX_NS)).strip()


_SKIP_TABLE_HEADERS = {"revision history", "revision", "document history", "change history"}


def _extract_docx_lines(blob: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as docx:
        root = ET.fromstring(docx.read("word/document.xml"))

    body = root.find(".//w:body", _DOCX_NS)
    if body is None:
        return []

    lines: list[str] = []
    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "tbl":
            first = _table_first_cell_text(child)
            if first.lower() in _SKIP_TABLE_HEADERS:
                continue
            for para in child.findall(".//w:p", _DOCX_NS):
                text = "".join((n.text or "") for n in para.findall(".//w:t", _DOCX_NS)).strip()
                if text:
                    lines.append(text)
        elif tag == "p":
            text = "".join((n.text or "") for n in child.findall(".//w:t", _DOCX_NS)).strip()
            if text:
                lines.append(text)
    return lines


def _extract_summary(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line.lower() == "description":
            for candidate in lines[index + 1:]:
                if candidate and not candidate.endswith(":"):
                    return candidate
    if len(lines) >= 3:
        return lines[2]
    if len(lines) >= 2:
        return lines[1]
    return lines[0] if lines else ""


def _render_content(lines: list[str]) -> str:
    if not lines:
        return ""
    if len(lines) <= 2:
        return "\n\n".join(lines)
    return "\n\n".join(lines[2:])


def _default_seed_archive_paths() -> list[Path]:
    backend_dir = Path(__file__).resolve().parent
    repo_root = backend_dir.parent
    env_path = os.getenv("KB_ARTICLE_ARCHIVE", "").strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend([
        repo_root / "OIT_KB_Articles.zip",
        Path("/app/OIT_KB_Articles.zip"),
    ])
    return candidates


_SUPPORTED_SOP_EXTENSIONS = {".docx", ".txt", ".pdf"}


def extract_sop_text(filename: str, content: bytes) -> str:
    """Extract plain text from a DOCX, TXT, or PDF upload."""
    ext = Path(filename).suffix.lower()
    if ext == ".docx":
        lines = _extract_docx_lines(content)
        return "\n\n".join(lines)
    if ext == ".txt":
        return content.decode("utf-8", errors="replace")
    if ext == ".pdf":
        return _extract_pdf_text(content)
    raise ValueError(f"Unsupported file type '{ext}'. Please upload a .docx, .txt, or .pdf file.")


def _extract_pdf_text(content: bytes) -> str:
    try:
        import io
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF support requires pypdf (pip install pypdf)") from exc
    reader = PdfReader(io.BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())


class KnowledgeBaseStore:
    """SQLite persistence and simple retrieval for KB articles."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "knowledge_base.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS kb_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    code TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    request_type TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    source_filename TEXT NOT NULL DEFAULT '',
                    source_ticket_key TEXT NOT NULL DEFAULT '',
                    imported_from_seed INTEGER NOT NULL DEFAULT 0,
                    ai_generated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_articles_request_type ON kb_articles(request_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_articles_slug ON kb_articles(slug)"
            )

    def _row_to_article(self, row: sqlite3.Row | tuple) -> KnowledgeBaseArticle:
        return KnowledgeBaseArticle(
            id=row[0],
            slug=row[1],
            code=row[2],
            title=row[3],
            request_type=row[4],
            summary=row[5],
            content=row[6],
            source_filename=row[7],
            source_ticket_key=row[8],
            imported_from_seed=bool(row[9]),
            ai_generated=bool(row[10]),
            created_at=row[11],
            updated_at=row[12],
        )

    def count_articles(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM kb_articles").fetchone()
        return int(row[0]) if row else 0

    def _slug_exists(self, slug: str, article_id: int | None = None) -> bool:
        with self._conn() as conn:
            if article_id is None:
                row = conn.execute("SELECT 1 FROM kb_articles WHERE slug = ?", (slug,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM kb_articles WHERE slug = ? AND id != ?",
                    (slug, article_id),
                ).fetchone()
        return row is not None

    def _unique_slug(self, title: str, article_id: int | None = None) -> str:
        base = _slugify(title)
        slug = base
        suffix = 2
        while self._slug_exists(slug, article_id=article_id):
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    def list_articles(
        self,
        *,
        search: str = "",
        request_type: str = "",
    ) -> list[KnowledgeBaseArticle]:
        sql = (
            "SELECT id, slug, code, title, request_type, summary, content, "
            "source_filename, source_ticket_key, imported_from_seed, ai_generated, created_at, updated_at "
            "FROM kb_articles"
        )
        clauses: list[str] = []
        params: list[str] = []
        if request_type:
            clauses.append("request_type = ?")
            params.append(request_type)
        if search:
            term = f"%{search.lower()}%"
            clauses.append(
                "(LOWER(title) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(content) LIKE ? OR LOWER(code) LIKE ?)"
            )
            params.extend([term, term, term, term])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY request_type ASC, title ASC, id ASC"

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_article(row) for row in rows]

    def get_article(self, article_id: int) -> KnowledgeBaseArticle | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, slug, code, title, request_type, summary, content, "
                "source_filename, source_ticket_key, imported_from_seed, ai_generated, created_at, updated_at "
                "FROM kb_articles WHERE id = ?",
                (article_id,),
            ).fetchone()
        return self._row_to_article(row) if row else None

    def create_article(
        self,
        body: KnowledgeBaseArticleUpsertRequest,
        *,
        code: str = "",
        source_filename: str = "",
        source_ticket_key: str = "",
        imported_from_seed: bool = False,
        ai_generated: bool = False,
    ) -> KnowledgeBaseArticle:
        now = _utc_now()
        title = body.title.strip()
        article = KnowledgeBaseArticle(
            slug=self._unique_slug(title),
            code=code.strip(),
            title=title,
            request_type=(body.request_type or "").strip(),
            summary=(body.summary or "").strip(),
            content=(body.content or "").strip(),
            source_filename=source_filename.strip(),
            source_ticket_key=(source_ticket_key or body.source_ticket_key or "").strip(),
            imported_from_seed=imported_from_seed,
            ai_generated=ai_generated,
            created_at=now,
            updated_at=now,
        )

        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO kb_articles
                (slug, code, title, request_type, summary, content, source_filename, source_ticket_key,
                 imported_from_seed, ai_generated, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    article.slug,
                    article.code,
                    article.title,
                    article.request_type,
                    article.summary,
                    article.content,
                    article.source_filename,
                    article.source_ticket_key,
                    int(article.imported_from_seed),
                    int(article.ai_generated),
                    article.created_at,
                    article.updated_at,
                ),
            )
            article.id = int(cur.lastrowid)
        return article

    def update_article(
        self,
        article_id: int,
        body: KnowledgeBaseArticleUpsertRequest,
        *,
        ai_generated: bool | None = None,
        source_ticket_key: str | None = None,
    ) -> KnowledgeBaseArticle | None:
        existing = self.get_article(article_id)
        if not existing:
            return None

        title = body.title.strip()
        slug = self._unique_slug(title, article_id=article_id)
        updated = _utc_now()
        merged_ai_generated = existing.ai_generated if ai_generated is None else ai_generated
        merged_ticket_key = (
            source_ticket_key.strip()
            if source_ticket_key is not None
            else (body.source_ticket_key or existing.source_ticket_key).strip()
        )

        with self._conn() as conn:
            conn.execute(
                """UPDATE kb_articles
                SET slug = ?, title = ?, request_type = ?, summary = ?, content = ?,
                    source_ticket_key = ?, ai_generated = ?, updated_at = ?
                WHERE id = ?""",
                (
                    slug,
                    title,
                    (body.request_type or "").strip(),
                    (body.summary or "").strip(),
                    (body.content or "").strip(),
                    merged_ticket_key,
                    int(merged_ai_generated),
                    updated,
                    article_id,
                ),
            )
        return self.get_article(article_id)

    def find_relevant_articles(
        self,
        *,
        request_type: str = "",
        query_text: str = "",
        limit: int = 3,
    ) -> list[KnowledgeBaseArticle]:
        articles = self.list_articles()
        if not articles:
            return []

        query_tokens = _tokenize(" ".join(part for part in [request_type, query_text] if part))
        scored: list[tuple[int, KnowledgeBaseArticle]] = []
        for article in articles:
            score = 0
            if request_type and article.request_type.lower() == request_type.lower():
                score += 200
            if request_type and article.title.lower() == request_type.lower():
                score += 80
            title_tokens = _tokenize(article.title)
            summary_tokens = _tokenize(article.summary)
            content_tokens = _tokenize(article.content)
            if query_tokens:
                score += 8 * len(query_tokens & title_tokens)
                score += 5 * len(query_tokens & summary_tokens)
                score += min(25, 2 * len(query_tokens & content_tokens))
            if score > 0:
                scored.append((score, article))

        scored.sort(key=lambda item: (-item[0], item[1].title.lower(), item[1].id or 0))
        return [article for _, article in scored[:limit]]

    def delete_article(self, article_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM kb_articles WHERE id = ?", (article_id,))
        return cur.rowcount > 0

    def find_default_target_article(self, request_type: str) -> KnowledgeBaseArticle | None:
        if not request_type:
            return None
        matches = self.list_articles(request_type=request_type)
        return matches[0] if matches else None

    def ensure_seed_articles(self) -> int:
        if self.count_articles() > 0:
            return 0
        archive_path = next((path for path in _default_seed_archive_paths() if path.is_file()), None)
        if not archive_path:
            logger.info("KB seed archive not found; skipping initial import")
            return 0
        imported = self.import_seed_archive(archive_path)
        if imported:
            logger.info("KB: imported %d seed articles from %s", imported, archive_path)
        return imported

    def import_seed_archive(self, archive_path: Path) -> int:
        imported = 0
        with zipfile.ZipFile(archive_path) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".docx")]
            for name in names:
                code = Path(name).stem.split("_", 1)[0]
                if code not in _REQUEST_TYPE_BY_CODE:
                    continue
                lines = _extract_docx_lines(archive.read(name))
                if not lines:
                    continue

                title = lines[1].strip() if len(lines) > 1 else _REQUEST_TYPE_BY_CODE[code]
                request_type = _REQUEST_TYPE_BY_CODE[code]
                summary = _extract_summary(lines)
                content = _render_content(lines)
                article = KnowledgeBaseArticleUpsertRequest(
                    title=title,
                    request_type=request_type,
                    summary=summary,
                    content=content,
                )
                self.create_article(
                    article,
                    code=code,
                    source_filename=name,
                    imported_from_seed=True,
                )
                imported += 1
        return imported


kb_store = KnowledgeBaseStore()
