"""
Batch-import SOP files from a directory into the knowledge base.

Usage:
    python backend/scripts/import_sops.py <directory> [--ai] [--dry-run]

Options:
    --ai        Use Ollama to convert each SOP to structured markdown (slower, uses local AI runtime)
    --dry-run   List files that would be imported without writing anything

Without --ai, raw text is extracted and stored as-is. Use "Reformat with AI"
in the KB UI afterwards to structure individual articles.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow running from repo root or backend/
_here = Path(__file__).resolve().parent
_backend = _here.parent
sys.path.insert(0, str(_backend))

from config import DATA_DIR  # noqa: E402 — must come after path fix
from knowledge_base import KnowledgeBaseStore, extract_sop_text  # noqa: E402
from models import KnowledgeBaseArticleUpsertRequest  # noqa: E402

SKIP_PATTERNS = {"template", "~$", ".tmp"}
SUPPORTED_EXTS = {".docx", ".pdf", ".txt"}


def _should_skip(path: Path) -> bool:
    name_lower = path.name.lower()
    return any(p in name_lower for p in SKIP_PATTERNS)


def _collect_files(root: Path) -> list[Path]:
    files = [
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTS
        and not _should_skip(p)
    ]
    # Deduplicate by stem (prefer shorter path = less nested = more canonical)
    seen: dict[str, Path] = {}
    for f in sorted(files, key=lambda p: len(p.parts)):
        stem = f.stem.lower().strip()
        if stem not in seen:
            seen[stem] = f
    return sorted(seen.values(), key=lambda p: p.name.lower())


def _already_imported(store: KnowledgeBaseStore, filename: str) -> bool:
    articles = store.list_articles()
    return any(a.source_filename == filename for a in articles)


def _safe_title(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-import SOPs into the KB")
    parser.add_argument("directory", help="Path to SOP directory")
    parser.add_argument("--ai", action="store_true", help="Use AI to convert each SOP")
    parser.add_argument("--dry-run", action="store_true", help="List files only, no writes")
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    files = _collect_files(root)
    print(f"Found {len(files)} unique SOP files in {root}")

    if args.dry_run:
        for f in files:
            print(f"  {f.relative_to(root)}")
        return

    store = KnowledgeBaseStore()
    ai_model_id: str | None = None

    if args.ai:
        from ai_client import get_available_models, draft_kb_from_sop
        models = get_available_models()
        if not models:
            print("Error: --ai requires Ollama to be running with at least one available local model", file=sys.stderr)
            sys.exit(1)
        ai_model_id = models[0].id
        print(f"AI mode: using {ai_model_id}")

    imported = skipped = errors = 0

    for i, path in enumerate(files, 1):
        rel = str(path.relative_to(root))
        prefix = f"[{i:3d}/{len(files)}]"

        if _already_imported(store, rel):
            print(f"{prefix} SKIP (already imported)  {rel}")
            skipped += 1
            continue

        try:
            content = path.read_bytes()
            text = extract_sop_text(path.name, content)
        except Exception as exc:
            print(f"{prefix} ERROR extracting {rel}: {exc}")
            errors += 1
            continue

        if not text.strip():
            print(f"{prefix} SKIP (no text extracted) {rel}")
            skipped += 1
            continue

        if args.ai and ai_model_id:
            try:
                from ai_client import draft_kb_from_sop
                draft = draft_kb_from_sop(text, path.name, ai_model_id)
                body = KnowledgeBaseArticleUpsertRequest(
                    title=draft.title,
                    request_type=draft.request_type,
                    summary=draft.summary,
                    content=draft.content,
                )
                store.create_article(body, source_filename=rel, ai_generated=True)
                print(f"{prefix} AI   {rel!r:60s}  →  {draft.title[:60]}")
                time.sleep(0.5)  # mild rate-limit protection
            except Exception as exc:
                print(f"{prefix} ERROR (AI) {rel}: {exc}")
                errors += 1
                continue
        else:
            title = _safe_title(path)
            body = KnowledgeBaseArticleUpsertRequest(
                title=title,
                content=text,
            )
            store.create_article(body, source_filename=rel)
            print(f"{prefix} OK   {rel}")

        imported += 1

    print(f"\nDone: {imported} imported, {skipped} skipped, {errors} errors.")


if __name__ == "__main__":
    main()
