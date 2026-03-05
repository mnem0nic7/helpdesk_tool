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

# Build and restart
echo ">>> Building Docker image..."
docker compose build $BUILD_FLAGS

echo ">>> Stopping old container (if running)..."
docker compose down

echo ">>> Starting new container..."
docker compose up -d

# Health check — wait up to 30 seconds
echo ">>> Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:3002/api/health > /dev/null 2>&1; then
        echo ""
        echo "=== DEPLOYED SUCCESSFULLY ==="
        echo "  Dashboard: http://localhost:3002"
        echo "  Health:    http://localhost:3002/api/health"
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
