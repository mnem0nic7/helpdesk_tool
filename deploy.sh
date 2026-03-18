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
