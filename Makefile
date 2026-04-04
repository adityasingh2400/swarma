.PHONY: start pull clean build

PYTHON := /Library/Frameworks/Python.framework/Versions/3.12/bin/python3

start: pull build
	@echo "\n  Starting ReRoute...\n"
	$(PYTHON) run.py

build:
	@echo "  Building frontend..."
	@cd frontend/mac && npm run build

pull:
	@git stash drop 2>/dev/null || true
	@git checkout -- . 2>/dev/null || true
	@git pull origin main --ff-only 2>/dev/null || true

clean:
	@git stash drop 2>/dev/null || true
	@git checkout -- .
	@echo "Clean — all local changes reset to remote."
