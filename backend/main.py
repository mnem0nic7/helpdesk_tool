"""FastAPI backend for the OIT Helpdesk Dashboard."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes_metrics import router as metrics_router
from routes_tickets import router as tickets_router
from routes_actions import router as actions_router
from routes_export import router as export_router

app = FastAPI(title="OIT Helpdesk Dashboard API", version="0.1.0")

# ---------------------------------------------------------------------------
# CORS – allow the Vite dev-server and the Docker/nginx front-end
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Docker (nginx)
        "http://localhost:3002",  # Docker (nginx, alternate port)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(metrics_router)
app.include_router(tickets_router)
app.include_router(actions_router)
app.include_router(export_router)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entrypoint (python main.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    reload = os.getenv("DASHBOARD_DEV", "0") == "1"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload)
