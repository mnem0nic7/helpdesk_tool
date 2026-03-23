from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from starlette.testclient import TestClient


def _ensure_route(app, path: str, endpoint, *, methods: list[str] | None = None) -> None:
    if any(getattr(route, "path", None) == path for route in app.routes):
        return
    app.add_api_route(path, endpoint, methods=methods or ["GET"])


def _build_client() -> TestClient:
    from auth import create_session
    import main

    mock_technician_scoring_manager = MagicMock()
    mock_technician_scoring_manager.start_worker = AsyncMock()
    mock_technician_scoring_manager.stop_worker = AsyncMock()
    main.technician_scoring_manager = mock_technician_scoring_manager

    client = TestClient(main.app, raise_server_exceptions=False)
    sid = create_session("test@example.com", "Test User")
    client.cookies.set("session_id", sid)
    return client


def test_http_exceptions_are_logged(caplog):
    from main import app

    async def raise_teapot():
        raise HTTPException(status_code=418, detail="teapot")

    _ensure_route(app, "/api/test-error-logging/http", raise_teapot)
    client = _build_client()

    with caplog.at_level(logging.WARNING):
        response = client.get("/api/test-error-logging/http")

    assert response.status_code == 418
    assert any(
        "HTTP 418 for GET /api/test-error-logging/http: teapot" in record.getMessage()
        for record in caplog.records
    )


def test_request_validation_errors_are_logged(caplog):
    from main import app

    async def typed_route(count: int):
        return {"count": count}

    _ensure_route(app, "/api/test-error-logging/validation", typed_route)
    client = _build_client()

    with caplog.at_level(logging.WARNING):
        response = client.get("/api/test-error-logging/validation?count=bad")

    assert response.status_code == 422
    assert any(
        "Request validation failed for GET /api/test-error-logging/validation?count=bad" in record.getMessage()
        for record in caplog.records
    )


def test_unhandled_exceptions_are_logged(caplog):
    from main import app

    async def raise_runtime_error():
        raise RuntimeError("boom")

    _ensure_route(app, "/api/test-error-logging/unhandled", raise_runtime_error)
    client = _build_client()

    with caplog.at_level(logging.ERROR):
        response = client.get("/api/test-error-logging/unhandled")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert any(
        "Unhandled exception for GET /api/test-error-logging/unhandled" in record.getMessage()
        for record in caplog.records
    )
