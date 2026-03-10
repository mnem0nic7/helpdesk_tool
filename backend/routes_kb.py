"""API routes for the internal knowledge base."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from ai_client import draft_kb_article, draft_kb_from_sop, get_available_models, reformat_kb_article_content
from auth import require_admin
from jira_client import JiraClient
from knowledge_base import extract_sop_text, kb_store
from metrics import _is_open
from models import (
    KnowledgeBaseArticle,
    KnowledgeBaseArticleUpsertRequest,
    KnowledgeBaseDraft,
    KnowledgeBaseDraftRequest,
)
from request_type import extract_request_type_name_from_fields
from site_context import get_current_site_scope, get_scoped_issues

router = APIRouter(prefix="/api/kb")

_client = JiraClient()


def _ensure_primary_site() -> None:
    if get_current_site_scope() != "primary":
        raise HTTPException(status_code=404, detail="Knowledge base is only available on the primary site")


@router.get("/articles")
async def list_articles(
    search: str = Query(default=""),
    request_type: str = Query(default=""),
) -> list[KnowledgeBaseArticle]:
    _ensure_primary_site()
    return kb_store.list_articles(search=search.strip(), request_type=request_type.strip())


@router.get("/articles/{article_id}")
async def get_article(article_id: int) -> KnowledgeBaseArticle:
    _ensure_primary_site()
    article = kb_store.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"KB article {article_id} not found")
    return article


@router.post("/articles")
async def create_article(
    body: KnowledgeBaseArticleUpsertRequest,
    _admin: dict[str, Any] = Depends(require_admin),
) -> KnowledgeBaseArticle:
    _ensure_primary_site()
    return kb_store.create_article(body)


@router.put("/articles/{article_id}")
async def update_article(
    article_id: int,
    body: KnowledgeBaseArticleUpsertRequest,
    _admin: dict[str, Any] = Depends(require_admin),
) -> KnowledgeBaseArticle:
    _ensure_primary_site()
    article = kb_store.update_article(article_id, body)
    if not article:
        raise HTTPException(status_code=404, detail=f"KB article {article_id} not found")
    return article


@router.delete("/articles/{article_id}")
async def delete_article(
    article_id: int,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, bool]:
    _ensure_primary_site()
    if not kb_store.delete_article(article_id):
        raise HTTPException(status_code=404, detail=f"KB article {article_id} not found")
    return {"deleted": True}


@router.post("/articles/from-sop")
async def draft_from_sop(
    file: UploadFile = File(...),
    _admin: dict[str, Any] = Depends(require_admin),
) -> KnowledgeBaseDraft:
    """Upload a DOCX, PDF, or TXT SOP and convert it to a KB article draft using AI."""
    _ensure_primary_site()
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")
    filename = file.filename or "upload"
    try:
        text = extract_sop_text(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from the uploaded file")
    available = get_available_models()
    if not available:
        raise HTTPException(status_code=400, detail="No AI model available to convert the SOP")
    return draft_kb_from_sop(text, filename, available[0].id)


@router.post("/articles/reformat-seeded")
async def reformat_seeded_articles(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, int]:
    """Reformat all seed-imported KB articles as structured markdown using AI."""
    _ensure_primary_site()
    available = get_available_models()
    if not available:
        raise HTTPException(status_code=400, detail="No AI model available to reformat articles")
    model_id = available[0].id
    seeded = [a for a in kb_store.list_articles() if a.imported_from_seed]
    count = 0
    for article in seeded:
        try:
            new_content = reformat_kb_article_content(article, model_id)
            if new_content:
                from models import KnowledgeBaseArticleUpsertRequest
                kb_store.update_article(
                    article.id,  # type: ignore[arg-type]
                    KnowledgeBaseArticleUpsertRequest(
                        title=article.title,
                        request_type=article.request_type,
                        summary=article.summary,
                        content=new_content,
                        source_ticket_key=article.source_ticket_key or None,
                    ),
                    ai_generated=True,
                )
                count += 1
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to reformat article %s: %s", article.id, exc)
    return {"reformatted": count}


@router.post("/articles/{article_id}/reformat")
async def reformat_article(
    article_id: int,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    """Reformat a single KB article's content as structured markdown using AI."""
    _ensure_primary_site()
    article = kb_store.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"KB article {article_id} not found")
    available = get_available_models()
    if not available:
        raise HTTPException(status_code=400, detail="No AI model available")
    new_content = reformat_kb_article_content(article, available[0].id)
    return {"content": new_content}


@router.post("/articles/draft-from-ticket")
async def draft_article_from_ticket(
    body: KnowledgeBaseDraftRequest,
    _admin: dict[str, Any] = Depends(require_admin),
) -> KnowledgeBaseDraft:
    _ensure_primary_site()

    issues_by_key = {
        issue.get("key", ""): issue
        for issue in get_scoped_issues()
        if issue.get("key")
    }
    issue = issues_by_key.get(body.key)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Ticket {body.key} is not available on this site")
    if _is_open(issue):
        raise HTTPException(status_code=400, detail="KB drafts can only be generated from closed tickets")

    available = get_available_models()
    if not available:
        raise HTTPException(
            status_code=400,
            detail="No AI model available. Configure an API key before generating KB drafts.",
        )

    available_ids = {model.id for model in available}
    model_id = body.model or available[0].id
    if model_id not in available_ids:
        raise HTTPException(status_code=400, detail=f"Model '{model_id}' is not available")

    target_article = None
    if body.article_id is not None:
        target_article = kb_store.get_article(body.article_id)
        if not target_article:
            raise HTTPException(status_code=404, detail=f"KB article {body.article_id} not found")
    else:
        target_article = kb_store.find_default_target_article(
            extract_request_type_name_from_fields(issue.get("fields", {}))
        )

    request_comments = _client.get_request_comments(body.key)
    return draft_kb_article(issue, request_comments, model_id, target_article)
