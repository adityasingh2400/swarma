#!/usr/bin/env bash
set -e

PORT_BACKEND=8080
PORT_FRONTEND=5173

# ── Kill stale processes on our ports ───────────────────────────────────────
echo "  Stopping existing servers..."
for pid in $(netstat -ano 2>/dev/null | grep ":${PORT_BACKEND} " | awk '{print $NF}' | sort -u); do
    taskkill //PID "$pid" //F >/dev/null 2>&1 || true
done
for pid in $(netstat -ano 2>/dev/null | grep ":${PORT_FRONTEND} " | awk '{print $NF}' | sort -u); do
    taskkill //PID "$pid" //F >/dev/null 2>&1 || true
done
sleep 0.5

# ── Install / sync dependencies ─────────────────────────────────────────────
if [ ! -d .venv ]; then
    echo "  Creating virtualenv..."
    python -m venv .venv
fi
echo "  Syncing dependencies..."
source .venv/Scripts/activate
pip install -q -r requirements.txt 2>&1 | tail -1

# ── Build frontend ───────────────────────────────────────────────────────────
echo "  Building frontend..."
pushd frontend/mac > /dev/null
npm install --silent
npm run build 2>&1 | tail -3
popd > /dev/null

# ── Warm-up ──────────────────────────────────────────────────────────────────
PYTHONUTF8=1 python scripts/warmup.py

# ── Launch servers ───────────────────────────────────────────────────────────
echo ""
echo "  Launching backend (:${PORT_BACKEND}) + frontend (:${PORT_FRONTEND})..."
echo ""

source .venv/Scripts/activate
PYTHONUTF8=1 python run.py &
sleep 2

cd frontend/mac && npx vite --force --port "$PORT_FRONTEND" &
sleep 2

echo ""
echo "  ──────────────────────────────────────"
echo -e "  \033[92m✓\033[0m \033[1mREADY\033[0m"
echo ""
echo "    App:     http://localhost:${PORT_FRONTEND}/"
echo "    Backend: http://localhost:${PORT_BACKEND}/"
echo "    Mock:    http://localhost:${PORT_FRONTEND}/?mock"
echo "    Preview: http://localhost:${PORT_FRONTEND}/?preview=concierge"
echo "  ──────────────────────────────────────"
echo ""
echo "  Press Ctrl+C to stop all servers."
wait
