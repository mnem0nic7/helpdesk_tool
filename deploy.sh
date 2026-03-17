#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# deploy.sh — Build and deploy OIT Helpdesk Dashboard
# Usage: ./deploy.sh [--no-cache]
# =============================================================================

cd "$(dirname "$0")"

BUILD_FLAGS=""
[[ "${1:-}" == "--no-cache" ]] && BUILD_FLAGS="--no-cache"

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
echo ">>> Building Docker image..."
docker compose build $BUILD_FLAGS

echo ">>> Stopping old containers (if running)..."
docker compose down

echo ">>> Starting containers..."
docker compose up -d

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
