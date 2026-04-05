#!/usr/bin/env python3
"""Save marketplace cookies from your real Chrome browser.

Usage:
    1. Run: bash start_auth_chrome.sh     (launches Chrome with remote debugging)
    2. Log into Facebook, Depop in Chrome
    3. Run: source .venv/bin/activate && python3 scripts/save_auth.py
    4. Press Enter for each platform to save its cookies

Connects to your running Chrome via CDP (port 9222) so you get your
real profile with no automation detection.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

AUTH_DIR = Path(__file__).resolve().parent.parent / "auth"

PLATFORMS = {
    "facebook": {"domain": ".facebook.com", "check_url": "https://www.facebook.com"},
    "depop":    {"domain": ".depop.com",    "check_url": "https://www.depop.com"},
}

BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


async def main():
    from playwright.async_api import async_playwright

    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n  {BOLD}SwarmSell — Save Cookies from Chrome{RESET}")
    print(f"  {'─' * 38}")
    print(f"  Connecting to Chrome on port 9222...\n")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        except Exception as e:
            print(f"  {YELLOW}!{RESET} Can't connect to Chrome on port 9222.")
            print(f"  Run this first:  bash start_auth_chrome.sh")
            print(f"  Then log into all 4 platforms, then run this script.\n")
            print(f"  Error: {e}\n")
            return

        contexts = browser.contexts
        if not contexts:
            print(f"  {YELLOW}!{RESET} No browser contexts found. Open a tab first.\n")
            return

        ctx = contexts[0]
        print(f"  {GREEN}✓{RESET} Connected to Chrome ({len(ctx.pages)} tabs open)\n")

        pick = input(f"  Which platforms? (Enter for all, or comma-separated): ").strip()
        if pick:
            selected = [p.strip().lower() for p in pick.split(",") if p.strip().lower() in PLATFORMS]
        else:
            selected = list(PLATFORMS.keys())

        for platform in selected:
            info = PLATFORMS[platform]
            cookie_path = AUTH_DIR / f"{platform}-cookies.json"

            print(f"\n  {BOLD}── {platform.upper()} ──{RESET}")
            print(f"  Make sure you're logged into {info['check_url']} in Chrome.")
            input(f"  Press Enter to save {platform} cookies...")

            state = await ctx.storage_state()

            platform_cookies = [
                c for c in state.get("cookies", [])
                if info["domain"] in c.get("domain", "")
            ]
            platform_origins = [
                o for o in state.get("origins", [])
                if info["domain"].lstrip(".") in o.get("origin", "")
            ]

            filtered_state = {
                "cookies": platform_cookies,
                "origins": platform_origins,
            }

            cookie_path.write_text(json.dumps(filtered_state, indent=2))
            print(f"  {GREEN}✓{RESET} Saved {len(platform_cookies)} cookies → {cookie_path}")

        print(f"\n  {'─' * 38}")
        print(f"  {GREEN}✓{RESET} {BOLD}Done!{RESET} Restart the server to pick up cookies.\n")


if __name__ == "__main__":
    asyncio.run(main())
