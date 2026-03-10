from __future__ import annotations

from models import AIModel, KnowledgeBaseArticleUpsertRequest, KnowledgeBaseDraft


def test_kb_routes_list_articles_on_primary_site(test_client, monkeypatch, tmp_path):
    import routes_kb
    from knowledge_base import KnowledgeBaseStore

    store = KnowledgeBaseStore(str(tmp_path / "kb.db"))
    store.create_article(
        KnowledgeBaseArticleUpsertRequest(
            title="Email or Outlook",
            request_type="Email or Outlook",
            summary="Mailbox and client troubleshooting.",
            content="Restart Outlook and verify Exchange connectivity.",
        ),
        code="KB-EML-001",
        source_filename="KB-EML-001_Email_or_Outlook.docx",
        imported_from_seed=True,
    )
    monkeypatch.setattr(routes_kb, "kb_store", store)

    resp = test_client.get("/api/kb/articles")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Email or Outlook"
    assert data[0]["imported_from_seed"] is True


def test_kb_routes_are_hidden_on_oasisdev_site(test_client):
    resp = test_client.get("/api/kb/articles", headers={"x-forwarded-host": "oasisdev.movedocs.com"})

    assert resp.status_code == 404


def test_kb_draft_from_closed_ticket_uses_visible_closed_ticket(test_client, monkeypatch, tmp_path):
    import routes_kb
    from knowledge_base import KnowledgeBaseStore

    store = KnowledgeBaseStore(str(tmp_path / "kb.db"))
    article = store.create_article(
        KnowledgeBaseArticleUpsertRequest(
            title="Email or Outlook",
            request_type="Email or Outlook",
            summary="Mailbox and client troubleshooting.",
            content="Restart Outlook and verify Exchange connectivity.",
        ),
    )
    monkeypatch.setattr(routes_kb, "kb_store", store)
    monkeypatch.setattr(store, "find_default_target_article", lambda request_type: article)
    monkeypatch.setattr(routes_kb, "get_available_models", lambda: [AIModel(id="gpt-4o-mini", name="GPT-4o Mini", provider="openai")])
    monkeypatch.setattr(routes_kb._client, "get_request_comments", lambda key: [])
    monkeypatch.setattr(
        routes_kb,
        "draft_kb_article",
        lambda issue, request_comments, model_id, existing_article=None: KnowledgeBaseDraft(
            title="Email Sync Troubleshooting",
            request_type="Email or Outlook",
            summary="Troubleshoot Outlook sync and send issues.",
            content="Verify connectivity.\n\nRestart Outlook.",
            model_used=model_id,
            source_ticket_key=issue.get("key", ""),
            suggested_article_id=existing_article.id if existing_article else None,
            suggested_article_title=existing_article.title if existing_article else "",
            recommended_action="update_existing" if existing_article else "create_new",
            change_summary="Adds Outlook restart guidance.",
        ),
    )

    resp = test_client.post("/api/kb/articles/draft-from-ticket", json={"key": "OIT-300"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Email Sync Troubleshooting"
    assert data["source_ticket_key"] == "OIT-300"
    assert data["suggested_article_id"] == article.id
