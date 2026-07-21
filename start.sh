#!/usr/bin/env bash
# start.sh — Launch Vane backend + frontend
#
# Usage:
#   ANTHROPIC_API_KEY=sk-ant-... ./start.sh
#
# Or with the key already exported:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   ./start.sh

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Key (optional) ───────────────────────────────────────────────────────────
# Only the chat endpoint needs a key. Simulation, temporal, stress tests, and
# the whole web UI run without one. The backend also reads ANTHROPIC_API_KEY
# from a .env file, so this is just a heads-up.
if [ -z "$ANTHROPIC_API_KEY" ] && ! grep -qs '^ANTHROPIC_API_KEY=.' .env; then
  echo "Note: ANTHROPIC_API_KEY not set — chat will be disabled; everything else works."
fi

# ── Trap to kill both processes on exit ──────────────────────────────────────
cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── Backend (FastAPI) ─────────────────────────────────────────────────────────
echo "Starting FastAPI backend on :8000 ..."
cd "$REPO_DIR"

# Install Python deps if needed
python -c "import fastapi" 2>/dev/null || pip install -r requirements.txt

ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait for backend to be ready
echo -n "Waiting for backend"
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo " ready."
    break
  fi
  echo -n "."
  sleep 1
done

# ── Frontend (Vite dev server) ────────────────────────────────────────────────
echo "Starting Vite frontend on :5173 ..."
cd "$REPO_DIR/web"

# Install npm deps if node_modules missing
[ -d node_modules ] || npm install

npm run dev &
FRONTEND_PID=$!

# ── Ready ─────────────────────────────────────────────────────────────────────
echo ""
echo "Vane"
echo "  Backend:   http://localhost:8000"
echo "  Frontend:  http://localhost:5173"
echo "  API docs:  http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop both services."

# Keep script alive until interrupted
wait "$BACKEND_PID" "$FRONTEND_PID"
