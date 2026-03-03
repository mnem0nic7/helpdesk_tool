#!/bin/bash
# start.sh — Launch OIT Helpdesk Dashboard
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
echo "============================================"
echo "  OIT Helpdesk Dashboard"
echo "============================================"
echo ""
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo ""
echo "  Press Ctrl+C to stop both servers"
echo "============================================"

# Start backend
cd "$DIR"
.venv/bin/python backend/main.py &
BACKEND_PID=$!

# Start frontend
cd "$DIR/frontend"
npm run dev -- --host 2>/dev/null &
FRONTEND_PID=$!

# Handle Ctrl+C
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "Done."
    exit 0
}
trap cleanup INT TERM

wait
