"""
Demo: concurrent CDP screencast streaming — validates the full pipeline
without requiring the orchestrator or a real video intake.

Opens N Playwright pages, starts CDP screencasting each, runs the FastAPI
server in the same event loop, then streams all feeds to the mock frontend.

Usage:
    python williamEdits/demo_stream.py

Then open in your browser:
    williamEdits/mock_frontend.html?job=demo
    (or http://localhost:8080 from any browser on the same machine)

Requirements:
    pip install uvicorn playwright
    playwright install chromium
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from playwright.async_api import async_playwright

import backend.streaming as streaming
from backend.server import app, _screenshot_push_loop

JOB_ID = "demo"

# Four agents navigating to distinct marketplace URLs — different content in each tile
DEMO_AGENTS: list[tuple[str, str]] = [
    ("ebay-research",     "https://ebay.com/sch/i.html?_nkw=iphone+13+pro+256gb&LH_Sold=1"),
    ("facebook-scout",    "https://facebook.com/marketplace/"),
    ("mercari-search",    "https://mercari.com/search/?keyword=iphone+13+pro"),
    ("amazon-parts",      "https://amazon.com/s?k=iphone+13+pro+replacement+screen"),
]


async def main() -> None:
    # Run uvicorn in the current event loop (disable its own signal handler so
    # our asyncio.run() stays in charge of the loop lifecycle)
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    server_task = asyncio.create_task(server.serve())

    # Give uvicorn a moment to bind the port
    await asyncio.sleep(1.0)
    print("Server:  http://localhost:8080")
    print(f"Frontend: open williamEdits/mock_frontend.html?job={JOB_ID}")
    print("Ctrl+C to stop.\n")

    # Start the screenshot push loop for our demo job.
    # The loop reads from streaming.frame_store (populated below) and delivers
    # binary frames to any WS client connected to /ws/demo/screenshots.
    push_task = asyncio.create_task(_screenshot_push_loop(JOB_ID))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        pages: list[tuple[str, object]] = []

        for agent_id, _ in DEMO_AGENTS:
            page = await context.new_page()
            await streaming.start_screencast(agent_id, page)
            pages.append((agent_id, page))
            print(f"Screencast started: {agent_id}")

        # Navigate all pages concurrently
        print("Navigating all pages...")
        await asyncio.gather(*[
            page.goto(url, wait_until="domcontentloaded")
            for (_, page), (__, url) in zip(pages, DEMO_AGENTS)
        ])
        print(f"All {len(pages)} pages loaded. Streaming to mock frontend.\n")

        try:
            # Keep running until interrupted
            while True:
                await asyncio.sleep(5)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass

        print("\nCleaning up...")
        for agent_id, _ in pages:
            await streaming.stop_screencast(agent_id)
        await context.close()
        await browser.close()

    push_task.cancel()
    server.should_exit = True
    server_task.cancel()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
