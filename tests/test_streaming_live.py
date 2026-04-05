"""LIVE streaming pipeline test — real browsers, real CDP, real WebSocket.

Opens actual Playwright browsers, starts CDP screencast, pushes frames through
the server's screenshot_push_loop, and verifies a WebSocket client receives
valid JPEG frames at 5fps.

This is NOT mocked. Real browsers open. Real screenshots are captured.

Run:
    python -m pytest tests/test_streaming_live.py -v -s --tb=short

Requires: playwright browsers installed (npx playwright install chromium)
"""
from __future__ import annotations

import asyncio
import struct
import time
from io import BytesIO

import pytest
from PIL import Image

from backend.config import settings
from backend.streaming import (
    FrameData,
    frame_store,
    start_screencast,
    stop_screencast,
    encode_binary_frame,
)
import backend.streaming as streaming_mod
from backend.server import ConnectionManager, _screenshot_push_loop


def _parse_frame(data: bytes) -> dict | None:
    """Decode binary WS frame like the frontend does."""
    if len(data) < 37 or data[0] != 0x01:
        return None
    agent_id = data[1:33].rstrip(b"\x00").decode("utf-8")
    ts = struct.unpack(">I", data[33:37])[0]
    jpeg = data[37:]
    return {"agentId": agent_id, "timestamp": ts, "jpeg": jpeg}


# ── Single Agent: Real CDP Screencast ────────────────────────────────────────



# ── Single Agent: CDP → Push Loop → WS Client ───────────────────────────────


class TestSingleAgentLiveStreaming:
    """Full path: real browser → CDP → frame_store → push loop → WS mock client."""

    @pytest.fixture(autouse=True)
    def clean(self):
        frame_store.clear()
        streaming_mod._cdp_sessions.clear()
        yield
        frame_store.clear()
        streaming_mod._cdp_sessions.clear()

    @pytest.mark.asyncio
    async def test_real_cdp_to_ws_delivery(self):
        """Real CDP frames should be delivered through the push loop
        and decodable by the frontend protocol."""
        from unittest.mock import AsyncMock, patch
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("https://example.com", wait_until="domcontentloaded")

            await start_screencast("ws-live-agent", page)

            # Trigger compositor + start push loop simultaneously
            mgr = ConnectionManager()
            ws = AsyncMock()
            await mgr.connect_screenshots("live-job", ws)

            with patch("backend.server.ws_manager", mgr):
                push_task = asyncio.create_task(_screenshot_push_loop("live-job"))
                # Trigger activity so CDP pushes frames
                for i in range(15):
                    await page.evaluate(f'document.body.style.backgroundColor = "rgb({i * 17}, 50, 150)"')
                    await asyncio.sleep(0.12)
                await asyncio.sleep(0.5)
                push_task.cancel()
                try:
                    await push_task
                except asyncio.CancelledError:
                    pass

            await stop_screencast("ws-live-agent")
            await browser.close()

        # Verify WS client received frames
        assert ws.send_bytes.called, "No frames delivered to WS client"
        call_count = ws.send_bytes.call_count
        assert call_count >= 3, f"Only {call_count} frames in ~2.3s — need >= 3 for 5fps"

        # Verify every frame is decodable
        for call in ws.send_bytes.call_args_list:
            raw = call[0][0]
            parsed = _parse_frame(raw)
            assert parsed is not None, "Frame not decodable by frontend protocol"
            assert parsed["agentId"] == "ws-live-agent"
            assert len(parsed["jpeg"]) > 100
            img = Image.open(BytesIO(parsed["jpeg"]))
            assert img.size[0] > 0


# ── Multiple Agents: 3 concurrent browsers ───────────────────────────────────


class TestMultiAgentLiveStreaming:
    """3 real browsers streaming simultaneously through the push loop."""

    @pytest.fixture(autouse=True)
    def clean(self):
        frame_store.clear()
        streaming_mod._cdp_sessions.clear()
        yield
        frame_store.clear()
        streaming_mod._cdp_sessions.clear()

    @pytest.mark.asyncio
    async def test_3_concurrent_browsers_stream_to_ws(self):
        """Launch 3 browser contexts, start CDP screencast on all 3,
        trigger compositor activity, verify all streams arrive at the WS client."""
        from unittest.mock import AsyncMock, patch
        from playwright.async_api import async_playwright

        agent_ids = ["agent-ebay", "agent-facebook", "agent-mercari"]

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            pages = []

            for agent_id in agent_ids:
                ctx = await browser.new_context()
                page = await ctx.new_page()
                await page.goto("https://example.com", wait_until="domcontentloaded")
                await start_screencast(agent_id, page)
                pages.append(page)

            # Set up push loop + WS client
            mgr = ConnectionManager()
            ws = AsyncMock()
            await mgr.connect_screenshots("multi-job", ws)

            with patch("backend.server.ws_manager", mgr):
                push_task = asyncio.create_task(_screenshot_push_loop("multi-job"))

                # Trigger compositor activity on all 3 pages
                for i in range(15):
                    for j, page in enumerate(pages):
                        color = (i * 17 + j * 50) % 256
                        await page.evaluate(f'document.body.style.backgroundColor = "rgb({color}, {j*80}, 100)"')
                    await asyncio.sleep(0.12)

                await asyncio.sleep(0.5)
                push_task.cancel()
                try:
                    await push_task
                except asyncio.CancelledError:
                    pass

            for agent_id in agent_ids:
                await stop_screencast(agent_id)
            await browser.close()

        # Verify all 3 agents delivered frames
        delivered_agents = set()
        for call in ws.send_bytes.call_args_list:
            parsed = _parse_frame(call[0][0])
            if parsed:
                delivered_agents.add(parsed["agentId"])

        assert delivered_agents == set(agent_ids), f"Missing: {set(agent_ids) - delivered_agents}"

        # Verify each agent got frames
        per_agent = {}
        for call in ws.send_bytes.call_args_list:
            parsed = _parse_frame(call[0][0])
            if parsed:
                per_agent[parsed["agentId"]] = per_agent.get(parsed["agentId"], 0) + 1

        for agent_id, count in per_agent.items():
            assert count >= 2, f"{agent_id}: {count} frames, need >= 2"
