"""FastAPI backend for the OIT Helpdesk Dashboard."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
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
from routes_triage import router as triage_router, technician_scoring_manager
from routes_auth import router as auth_router
from routes_sla import router as sla_router
from routes_alerts import router as alerts_router
from routes_kb import router as kb_router
from routes_azure import router as azure_router
from routes_azure_alerts import router as azure_alerts_router
from routes_user_admin import router as user_admin_router
from routes_user_exit import router as user_exit_router
from azure_alert_engine import start_azure_alert_loop, stop_azure_alert_loop
from azure_cost_exports import azure_cost_export_service
from issue_cache import cache
from azure_cache import azure_cache
from azure_vm_export_jobs import azure_vm_export_jobs
from user_admin_jobs import user_admin_jobs
from user_exit_workflows import user_exit_workflows
from knowledge_base import kb_store
from site_context import (
    get_current_site_scope,
    get_site_scope_from_request,
    reset_current_site_scope,
    set_current_site_scope,
)

logger = logging.getLogger(__name__)


def _default_kb_seed_status() -> dict[str, Any]:
    return {
        "ready": False,
        "message": "Knowledge base seed import queued",
        "imported_count": 0,
        "error": None,
    }


def _get_kb_seed_status(app: FastAPI) -> dict[str, Any]:
    status = getattr(app.state, "kb_seed_status", None)
    if isinstance(status, dict):
        return dict(status)
    default = _default_kb_seed_status()
    app.state.kb_seed_status = dict(default)
    return default


def _set_kb_seed_status(app: FastAPI, **updates: Any) -> None:
    status = _get_kb_seed_status(app)
    status.update(updates)
    app.state.kb_seed_status = status


def _register_app_task(app: FastAPI, task: asyncio.Task[Any]) -> None:
    tasks = getattr(app.state, "background_tasks", None)
    if tasks is None:
        tasks = set()
        app.state.background_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _start_deferred_services(app: FastAPI) -> None:
    """Start non-critical background services after the API is already serving."""
    await asyncio.sleep(0)

    starters: tuple[tuple[str, Any], ...] = (
        ("Azure cost export service", azure_cost_export_service.start),
        ("Azure VM export worker", azure_vm_export_jobs.start_worker),
        ("User admin worker", user_admin_jobs.start_worker),
        ("User exit workflow worker", user_exit_workflows.start_worker),
        ("Azure alert loop", start_azure_alert_loop),
    )

    for label, starter in starters:
        try:
            await starter()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to start %s", label)

    try:
        while not cache.initialized:
            ready = await cache.wait_until_initialized(timeout=5)
            if ready:
                break
            logger.info("Waiting for issue cache warm-up before starting technician scoring worker")
        await technician_scoring_manager.start_worker()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Failed to start technician scoring worker")


async def _seed_knowledge_base(app: FastAPI) -> None:
    _set_kb_seed_status(
        app,
        ready=False,
        message="Knowledge base seed import running in the background",
        imported_count=0,
        error=None,
    )
    try:
        imported = await asyncio.to_thread(kb_store.ensure_seed_articles)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Knowledge base seed import failed")
        _set_kb_seed_status(
            app,
            ready=False,
            message="Knowledge base seed import failed",
            imported_count=0,
            error=str(exc),
        )
        return

    message = "Knowledge base seed check complete"
    if imported:
        message = f"Imported {imported} knowledge base seed article(s)"
    _set_kb_seed_status(
        app,
        ready=True,
        message=message,
        imported_count=imported,
        error=None,
    )


def _build_readiness_payload(app: FastAPI) -> dict[str, Any]:
    scope = get_current_site_scope()
    issue_status = cache.status()
    azure_status = azure_cache.status()
    kb_status = _get_kb_seed_status(app)

    issue_ready = bool(issue_status.get("initialized"))
    issue_message = "Issue cache ready"
    if not issue_ready:
        issue_message = "Issue cache is warming"
    elif issue_status.get("refreshing"):
        issue_message = "Issue cache ready; background refresh in progress"

    azure_ready = bool(azure_status.get("initialized"))
    azure_message = "Azure cache ready"
    if not azure_status.get("configured", True):
        azure_message = "Azure cache credentials are not configured"
    elif not azure_ready:
        azure_message = "Azure cache is warming"
    elif azure_status.get("refreshing"):
        azure_message = "Azure cache ready; background refresh in progress"

    return {
        "status": "ready" if issue_ready else "warming",
        "site_scope": scope,
        "components": {
            "issue_cache": {
                "ready": issue_ready,
                "last_refresh": issue_status.get("last_refresh"),
                "message": issue_message,
            },
            "azure_cache": {
                "ready": azure_ready,
                "last_refresh": azure_status.get("last_refresh"),
                "message": azure_message,
            },
            "knowledge_base": {
                "ready": bool(kb_status.get("ready")),
                "message": str(kb_status.get("message") or ""),
            },
        },
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background cache refresh on startup, stop on shutdown."""
    app.state.background_tasks = set()
    app.state.kb_seed_status = _default_kb_seed_status()
    _register_app_task(app, asyncio.create_task(_seed_knowledge_base(app)))
    await cache.start_background_refresh()
    await azure_cache.start_background_refresh()
    _register_app_task(app, asyncio.create_task(_start_deferred_services(app)))
    yield
    await stop_azure_alert_loop()
    await user_exit_workflows.stop_worker()
    await user_admin_jobs.stop_worker()
    await technician_scoring_manager.stop_worker()
    await azure_vm_export_jobs.stop_worker()
    await azure_cost_export_service.stop()
    await azure_cache.stop_background_refresh()
    await cache.stop_background_refresh()
    background_tasks = list(getattr(app.state, "background_tasks", set()))
    for task in background_tasks:
        if not task.done():
            task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)


app = FastAPI(title="OIT Helpdesk Dashboard API", version="0.1.0", lifespan=lifespan)


def _request_label(request: Request) -> str:
    query = request.url.query
    path = request.url.path
    if query:
        path = f"{path}?{query}"
    return f"{request.method} {path}"

# ---------------------------------------------------------------------------
# Auth middleware — protects /api/* except public endpoints
# ---------------------------------------------------------------------------
_PUBLIC_PATHS = {
    "/api/health",
    "/api/health/ready",
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/me",
    "/api/auth/logout",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/")
        # Only protect /api/* paths (let frontend assets through)
        if path.startswith("/api") and path not in _PUBLIC_PATHS and not path.startswith("/api/user-exit/agent/"):
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


class ErrorLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled exception for %s", _request_label(request))
            raise


# ---------------------------------------------------------------------------
# Middleware stack (applied in reverse order — CORS outermost)
# ---------------------------------------------------------------------------
app.add_middleware(AuthMiddleware)
app.add_middleware(SiteContextMiddleware)
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY)
app.add_middleware(ErrorLoggingMiddleware)


@app.exception_handler(StarletteHTTPException)
async def log_http_exceptions(request: Request, exc: StarletteHTTPException):
    log = logger.error if exc.status_code >= 500 else logger.warning
    log("HTTP %s for %s: %s", exc.status_code, _request_label(request), exc.detail)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def log_request_validation_errors(request: Request, exc: RequestValidationError):
    logger.warning("Request validation failed for %s: %s", _request_label(request), exc.errors())
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(Exception)
async def log_unhandled_exceptions(request: Request, exc: Exception):
    logger.exception("Unhandled exception for %s", _request_label(request))
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

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
app.include_router(user_exit_router)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    scope = get_current_site_scope()
    return {"status": "ok", "site_scope": scope}


@app.get("/api/health/ready")
async def health_ready(request: Request) -> JSONResponse:
    payload = _build_readiness_payload(request.app)
    status_code = 200 if payload["status"] == "ready" else 503
    return JSONResponse(status_code=status_code, content=payload)


# ---------------------------------------------------------------------------
# Entrypoint (python main.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    reload = os.getenv("DASHBOARD_DEV", "0") == "1"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload)
