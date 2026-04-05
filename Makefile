.PHONY: start pull clean build deps warmup stop

ACTIVATE := source .venv/bin/activate
PORT_BACKEND := 8080
PORT_FRONTEND := 5173

# ── Main target: kill stale → deps → build → warm-up → server ────────────

start: stop deps build
	@$(ACTIVATE) && python3 scripts/warmup.py
	@echo "\n  Launching backend (:$(PORT_BACKEND)) + frontend (:$(PORT_FRONTEND))...\n"
	@$(ACTIVATE) && python3 run.py &
	@sleep 2
	@cd frontend/mac && npx vite --force --port $(PORT_FRONTEND) &
	@sleep 2
	@echo ""
	@echo "  ──────────────────────────────────────"
	@echo "  \033[92m✓\033[0m \033[1mREADY\033[0m"
	@echo ""
	@echo "    App:     http://localhost:$(PORT_FRONTEND)/"
	@echo "    Backend: http://localhost:$(PORT_BACKEND)/"
	@echo "    Mock:    http://localhost:$(PORT_FRONTEND)/?mock"
	@echo "    Preview: http://localhost:$(PORT_FRONTEND)/?preview=concierge"
	@echo "  ──────────────────────────────────────"
	@echo ""
	@echo "  Press Ctrl+C to stop all servers."
	@wait

# ── Kill anything on our ports ────────────────────────────────────────────

stop:
	@lsof -ti:$(PORT_BACKEND) 2>/dev/null | xargs kill 2>/dev/null || true
	@lsof -ti:$(PORT_FRONTEND) 2>/dev/null | xargs kill 2>/dev/null || true
	@pkill -f 'osascript.*set targetApp' 2>/dev/null || true
	@sleep 0.5

# ── Install / sync dependencies ───────────────────────────────────────────

deps:
	@if [ ! -d .venv ]; then \
		echo "  Creating virtualenv..."; \
		python3 -m venv .venv; \
	fi
	@echo "  Syncing dependencies..."
	@$(ACTIVATE) && pip install -q -r requirements.txt 2>&1 | tail -1

# ── Build frontend ────────────────────────────────────────────────────────

build:
	@echo "  Building frontend..."
	@cd frontend/mac && npm run build 2>&1 | tail -3

# ── Warm-up only (no server) ─────────────────────────────────────────────

warmup:
	@$(ACTIVATE) && python3 scripts/warmup.py

# ── Git helpers ───────────────────────────────────────────────────────────

pull:
	@git stash drop 2>/dev/null || true
	@git checkout -- . 2>/dev/null || true
	@git pull origin main --ff-only 2>/dev/null || true

clean:
	@git stash drop 2>/dev/null || true
	@git checkout -- .
	@echo "Clean — all local changes reset to remote."
