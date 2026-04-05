"""Pre-flight warm-up for SwarmSell.

Run via `make start` or `make warmup`.

Warms up the slow-to-init subsystems so the first pipeline run is fast:
  1. Environment check (.env, API keys, ffmpeg/ffprobe)
  2. Gemini API pool — init clients for all configured keys
  3. Arctic-Embed-XS — download + load model (~90MB first time, ~4s cached)
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="  %(message)s")
logger = logging.getLogger("warmup")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"
WARN = "\033[93m!\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"

errors: list[str] = []
warnings: list[str] = []


def step(label: str):
    print(f"  {BOLD}{'·':>2}{RESET} {label}...", end="", flush=True)

def ok(detail: str = ""):
    print(f" {PASS}{f' ({detail})' if detail else ''}")

def warn(detail: str):
    warnings.append(detail)
    print(f" {WARN} {detail}")

def fail(detail: str):
    errors.append(detail)
    print(f" {FAIL} {detail}")


def check_env():
    step("Checking .env")
    if not (ROOT / ".env").exists():
        fail(".env not found — copy .env.example and fill in keys")
        return
    from backend.config import settings
    if not settings.gemini_api_key:
        warn("GEMINI_API_KEY not set")
    else:
        ok()


def check_system_deps():
    import shutil
    for binary in ["ffmpeg", "ffprobe"]:
        step(f"Checking {binary}")
        if shutil.which(binary):
            ok()
        else:
            fail(f"{binary} not found on PATH")


def warm_gemini_pool():
    step("Warming Gemini API pool")
    try:
        from backend.intake import _gemini_pool
        _gemini_pool._ensure_init()
        count = _gemini_pool.key_count
        if count > 0:
            ok(f"{count} key{'s' if count != 1 else ''}")
        else:
            warn("no keys configured")
    except Exception as exc:
        warn(f"{exc}")


def warm_embed_model():
    step("Loading Arctic-Embed-XS model")
    t0 = time.time()
    try:
        from backend.intake import _embed_pool
        _embed_pool._ensure_init()
        ok(f"{time.time() - t0:.1f}s")
    except Exception as exc:
        warn(f"{exc}")


def main():
    t_start = time.time()
    print(f"\n  {BOLD}SwarmSell — Warm-up{RESET}")
    print(f"  {'─' * 28}\n")

    check_env()
    check_system_deps()

    step("Ensuring data directories")
    from backend.config import settings
    settings.ensure_dirs()
    ok()

    warm_gemini_pool()
    warm_embed_model()

    elapsed = time.time() - t_start
    print(f"\n  {'─' * 28}")
    if errors:
        print(f"  {FAIL} {BOLD}BLOCKED{RESET} — {len(errors)} error(s) ({elapsed:.1f}s)\n")
        sys.exit(1)
    elif warnings:
        print(f"  {WARN} {BOLD}READY{RESET} ({len(warnings)} warning{'s' if len(warnings) != 1 else ''}, {elapsed:.1f}s)\n")
    else:
        print(f"  {PASS} {BOLD}READY{RESET} — all systems go ({elapsed:.1f}s)\n")


if __name__ == "__main__":
    main()
