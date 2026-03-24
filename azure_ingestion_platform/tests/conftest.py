from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


@pytest.fixture
def platform_env(tmp_path, monkeypatch):
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'platform.db'}")
    monkeypatch.setenv("PLATFORM_ENTRA_CLIENT_ID", "platform-client-id")
    monkeypatch.setenv("PLATFORM_ENTRA_CLIENT_SECRET", "platform-client-secret")
    monkeypatch.setenv("PLATFORM_ENTRA_REDIRECT_URI", "http://testserver/api/v1/onboarding/callback")
    monkeypatch.setenv("PLATFORM_ENCRYPTION_KEY", "unit-test-encryption-key")
    for name in list(sys.modules):
        if name.startswith("azure_ingestion_platform"):
            del sys.modules[name]
    return tmp_path


@pytest.fixture
def platform_app(platform_env):
    db = importlib.import_module("azure_ingestion_platform.db")
    models = importlib.import_module("azure_ingestion_platform.models")
    main = importlib.import_module("azure_ingestion_platform.main")
    db.Base.metadata.create_all(db.engine)
    client = TestClient(main.app)
    return {
        "client": client,
        "db": db,
        "models": models,
        "main": main,
    }
