"""FastAPI backend for the OIT Helpdesk Dashboard."""

import logging
import os
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from auth import get_session
from config import APP_SECRET_KEY
from routes_metrics import router as metrics_router
from routes_tickets import router as tickets_router
from routes_actions import router as actions_router
from routes_export import router as export_router
from routes_cache import router as cache_router
from routes_chart import router as chart_router
from routes_triage import router as triage_router
from routes_auth import router as auth_router
from routes_sla import router as sla_router
from routes_alerts import router as alerts_router
from routes_kb import router as kb_router
from routes_azure import router as azure_router
from routes_azure_alerts import router as azure_alerts_router
from routes_user_admin import router as user_admin_router
from azure_alert_engine import start_azure_alert_loop, stop_azure_alert_loop
from issue_cache import cache
from azure_cache import azure_cache
from azure_vm_export_jobs import azure_vm_export_jobs
from user_admin_jobs import user_admin_jobs
from knowledge_base import kb_store
from site_context import (
    get_current_site_scope,
    get_site_scope_from_request,
    reset_current_site_scope,
    set_current_site_scope,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background cache refresh on startup, stop on shutdown."""
    kb_store.ensure_seed_articles()
    await cache.start_background_refresh()
    await azure_cache.start_background_refresh()
    await azure_vm_export_jobs.start_worker()
    await user_admin_jobs.start_worker()
    await start_azure_alert_loop()
    yield
    await stop_azure_alert_loop()
    await user_admin_jobs.stop_worker()
    await azure_vm_export_jobs.stop_worker()
    await azure_cache.stop_background_refresh()
    await cache.stop_background_refresh()


app = FastAPI(title="OIT Helpdesk Dashboard API", version="0.1.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Auth middleware — protects /api/* except public endpoints
# ---------------------------------------------------------------------------
_PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/me",
    "/api/auth/logout",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/")
        # Only protect /api/* paths (let frontend assets through)
        if path.startswith("/api") and path not in _PUBLIC_PATHS:
            sid = request.cookies.get("session_id")
            if not sid or not get_session(sid):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Not authenticated"},
                )
        return await call_next(request)


class SiteContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        scope = get_site_scope_from_request(request)
        request.state.site_scope = scope
        token = set_current_site_scope(scope)
        try:
            return await call_next(request)
        finally:
            reset_current_site_scope(token)


# ---------------------------------------------------------------------------
# Middleware stack (applied in reverse order — CORS outermost)
# ---------------------------------------------------------------------------
app.add_middleware(AuthMiddleware)
app.add_middleware(SiteContextMiddleware)
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY)

# ---------------------------------------------------------------------------
# CORS – allow the Vite dev-server, Docker/nginx, and production origin
# ---------------------------------------------------------------------------
_cors_origins = [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:3000",  # Docker (nginx)
    "http://localhost:3002",  # Docker (nginx, alternate port)
    "https://it-app.movedocs.com",
    "https://oasisdev.movedocs.com",
    "https://azure.movedocs.com",
]
_extra_origin = os.getenv("CORS_ORIGIN", "")
if _extra_origin:
    _cors_origins.append(_extra_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(metrics_router)
app.include_router(tickets_router)
app.include_router(actions_router)
app.include_router(export_router)
app.include_router(cache_router)
app.include_router(chart_router)
app.include_router(triage_router)
app.include_router(sla_router)
app.include_router(alerts_router)
app.include_router(kb_router)
app.include_router(azure_router)
app.include_router(azure_alerts_router)
app.include_router(user_admin_router)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    scope = get_current_site_scope()
    return {"status": "ok", "site_scope": scope}


# ---------------------------------------------------------------------------
# Entrypoint (python main.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    reload = os.getenv("DASHBOARD_DEV", "0") == "1"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload)
