#!/bin/bash
set -e

echo "═══════════════════════════════════════════════"
echo "  SwarmSell — Setup"
echo "═══════════════════════════════════════════════"
echo ""

cd "$(dirname "$0")/.."
ROOT=$(pwd)

# Python dependencies
echo "[1/4] Installing Python dependencies..."
pip install -r requirements.txt

# Frontend dependencies
echo "[2/4] Installing Mac dashboard dependencies..."
cd "$ROOT/frontend/mac"
npm install

# Build frontend
echo "[3/4] Building Mac dashboard..."
npm run build

# Create .env if missing
echo "[4/4] Checking environment..."
cd "$ROOT"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  → Created .env from .env.example"
    echo "  → Edit .env with your API keys before running"
else
    echo "  → .env already exists"
fi

# Ensure data directories
mkdir -p data/uploads data/frames data/optimized data/jobs

echo ""
echo "═══════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. Edit .env with your API keys"
echo "    2. Run: python run.py"
echo "    3. Open http://localhost:8080 on Mac"
echo "    4. Open http://localhost:8080/phone/ on phone"
echo "═══════════════════════════════════════════════"
