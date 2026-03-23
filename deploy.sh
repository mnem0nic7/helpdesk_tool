#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# deploy.sh — Build and deploy OIT Helpdesk Dashboard
# Usage: ./deploy.sh [--no-cache] [--full]
#   (default) rebuild dashboard only; Caddy stays up
#   --full     stop all containers, rebuild everything (use when Caddyfile changes)
#   --no-cache pass --no-cache to docker compose build
# =============================================================================

cd "$(dirname "$0")"

BUILD_FLAGS=""
FULL_REBUILD=0
for arg in "$@"; do
    [[ "$arg" == "--no-cache" ]] && BUILD_FLAGS="--no-cache"
    [[ "$arg" == "--full" ]]     && FULL_REBUILD=1
done

echo "=== OIT Helpdesk Dashboard — Deploy ==="

# Pre-flight checks
if [ ! -f backend/.env ]; then
    echo "ERROR: backend/.env not found."
    echo "  cp backend/.env.example backend/.env"
    echo "  Then fill in your production values."
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed."
    echo "  curl -fsSL https://get.docker.com | sh"
    exit 1
fi

echo ">>> Checking Ollama on the host..."
if ! curl -fsS http://127.0.0.1:11434/api/tags > /dev/null; then
    echo "ERROR: Ollama is not reachable on the host at http://127.0.0.1:11434."
    echo "  Start Ollama and make sure it is serving before deploying."
    exit 1
fi

# Build and restart
if [[ "$FULL_REBUILD" == "1" ]]; then
    echo ">>> Full rebuild: stopping all containers..."
    docker compose down
    echo ">>> Building all images..."
    docker compose build $BUILD_FLAGS
    echo ">>> Starting all containers..."
    docker compose up -d
else
    echo ">>> Building dashboard image (Caddy stays up)..."
    docker compose build $BUILD_FLAGS dashboard
    echo ">>> Restarting dashboard only..."
    docker compose up --no-deps -d dashboard
fi

echo ">>> Verifying dashboard container can reach Ollama..."
if ! docker compose exec -T dashboard python3 - <<'PY'
import os
import sys
import urllib.request
import json

base = os.environ.get("OLLAMA_BASE_URL", "").rstrip("/")
model = os.environ.get("OLLAMA_MODEL", "").strip()
if not base:
    print("OLLAMA_BASE_URL is not set in the dashboard container.")
    sys.exit(1)
if not model:
    print("OLLAMA_MODEL is not set in the dashboard container.")
    sys.exit(1)

url = f"{base}/api/tags"
try:
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status != 200:
            print(f"Ollama check returned HTTP {response.status} for {url}")
            sys.exit(1)
        payload = json.loads(response.read().decode("utf-8", "ignore"))
except Exception as exc:
    print(f"Failed to reach Ollama from dashboard container at {url}: {exc}")
    sys.exit(1)

print(f"Ollama reachable from dashboard container at {url}")
models = {entry.get("model") or entry.get("name") for entry in payload.get("models") or []}
print(f"Available Ollama models: {sorted(m for m in models if m)}")
if model not in models:
    print(f"Configured Ollama model '{model}' is not pulled on the host.")
    sys.exit(1)
PY
then
    echo "ERROR: Dashboard container cannot reach Ollama."
    echo "  Check docker networking, OLLAMA_BASE_URL, and that the configured model is pulled."
    exit 1
fi

# Health check — wait up to 120 seconds (first-time DNS-01 cert can take 30-90s)
echo ">>> Waiting for health check..."
for i in $(seq 1 120); do
    if curl -sf http://localhost:80/api/health > /dev/null 2>&1; then
        echo ""
        echo "=== DEPLOYED SUCCESSFULLY ==="
        echo "  Dashboard: https://it-app.movedocs.com"
        echo "  OasisDev:  https://oasisdev.movedocs.com"
        echo "  Azure:     https://azure.movedocs.com"
        echo "  Health:    https://it-app.movedocs.com/api/health"
        echo ""
        docker compose ps
        exit 0
    fi
    printf "."
    sleep 1
done

echo ""
echo "WARNING: Health check timed out. Check logs:"
echo "  docker compose logs -f"
exit 1
