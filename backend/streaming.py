"""CDP screencast capture + binary WebSocket framing.

Uses Chrome DevTools Protocol (CDP) Page.screencastFrame events for async
video broadcast — no polling. Each agent gets its own CDP session when its
browser page is ready; the browser pushes JPEG frames directly to the handler.

CDP scales frames to 320×240 before encoding — no server-side PIL processing.
The frame handler is a pure store: decode base64, write to frame_store.

Binary frame format:
  [0x01] [32-byte utf8 agentId null-padded] [4-byte uint32 BE timestamp] [JPEG bytes]
  Header total: 37 bytes.

Hook points — call these from the orchestrator:
  await streaming.start_screencast(agent_id, page, browser_session)
  await streaming.stop_screencast(agent_id)
"""
from __future__ import annotations

import asyncio
import base64
import logging
import struct
import time
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger("swarmsell.streaming")


# ── Frame Store ───────────────────────────────────────────────────────────────

@dataclass(slots=True)
class FrameData:
    jpeg: bytes
    ts: float


frame_store: dict[str, FrameData] = {}

# Active sessions — kept so stop_screencast can tear them down.
# Each entry is a dict with the info needed to stop/clean up.
_active: dict[str, dict] = {}


# ── Binary Frame Encoding ─────────────────────────────────────────────────────


def encode_binary_frame(agent_id: str, jpeg_bytes: bytes) -> bytes:
    """Pack a JPEG into the binary WS frame format."""
    agent_bytes = agent_id.encode("utf-8")[:32].ljust(32, b"\x00")
    ts = struct.pack(">I", int(time.time()) & 0xFFFFFFFF)
    return b"\x01" + agent_bytes + ts + jpeg_bytes


# ── CDP Screencast ────────────────────────────────────────────────────────────


def _store_frame(agent_id: str, params: dict) -> None:
    """Decode and store a screencast frame (shared by both backends)."""
    jpeg_bytes = base64.b64decode(params["data"])
    frame_store[agent_id] = FrameData(jpeg=jpeg_bytes, ts=time.time())


async def _start_via_browser_use(agent_id: str, browser_session, every_n: int) -> bool:
    """Try starting screencast via Browser-Use's cdp_use CDPClient.

    Returns True on success, False if this strategy doesn't apply.
    """
    if browser_session is None:
        return False

    try:
        bu_session = await browser_session.get_or_create_cdp_session()
    except Exception as exc:
        logger.debug("BrowserSession.get_or_create_cdp_session failed for %s: %s", agent_id, exc)
        return False

    cdp_client = getattr(bu_session, 'cdp_client', None)
    session_id = getattr(bu_session, 'session_id', None)

    if cdp_client is None or not hasattr(cdp_client, 'send_raw'):
        logger.debug("cdp_use client not usable for %s", agent_id)
        return False

    try:
        await cdp_client.send_raw("Page.startScreencast", {
            "format": "jpeg",
            "quality": settings.screenshot_grid_quality,
            "maxWidth": settings.screenshot_grid_width,
            "maxHeight": settings.screenshot_grid_height,
            "everyNthFrame": every_n,
        }, session_id=session_id)
    except Exception as exc:
        logger.debug("cdp_use startScreencast failed for %s: %s", agent_id, exc)
        return False

    def _on_frame(params: dict, evt_session_id: str | None = None) -> None:
        _store_frame(agent_id, params)
        # Ack the frame so Chrome keeps sending
        asyncio.ensure_future(
            cdp_client.send_raw(
                "Page.screencastFrameAck",
                {"sessionId": params["sessionId"]},
                session_id=session_id,
            )
        )

    cdp_client._event_registry.register("Page.screencastFrame", _on_frame)

    _active[agent_id] = {
        "type": "browser_use",
        "cdp_client": cdp_client,
        "session_id": session_id,
    }
    logger.info("CDP screencast started for %s via cdp_use (everyNthFrame=%d)", agent_id, every_n)
    return True


async def _start_via_playwright(agent_id: str, page, every_n: int) -> bool:
    """Try starting screencast via Playwright's CDP session.

    Returns True on success, False if this strategy doesn't apply.
    """
    try:
        ctx = getattr(page, 'context', None)
        if ctx is None and hasattr(page, '_impl_obj'):
            ctx = page._impl_obj.context
        if ctx is None:
            return False
        cdp = await ctx.new_cdp_session(page)
    except Exception as exc:
        logger.debug("Playwright CDP failed for %s: %s", agent_id, exc)
        return False

    try:
        await cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": settings.screenshot_grid_quality,
            "maxWidth": settings.screenshot_grid_width,
            "maxHeight": settings.screenshot_grid_height,
            "everyNthFrame": every_n,
        })
    except Exception as exc:
        logger.debug("Playwright startScreencast failed for %s: %s", agent_id, exc)
        return False

    async def _on_frame_async(params: dict) -> None:
        _store_frame(agent_id, params)
        try:
            await cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:
            pass

    def _on_frame(params: dict) -> None:
        asyncio.ensure_future(_on_frame_async(params))

    cdp.on("Page.screencastFrame", _on_frame)

    _active[agent_id] = {"type": "playwright", "cdp": cdp}
    logger.info("CDP screencast started for %s via Playwright (everyNthFrame=%d)", agent_id, every_n)
    return True


async def start_screencast(agent_id: str, page, browser_session=None) -> None:
    """Start a CDP screencast for one agent.

    Tries Browser-Use's cdp_use client first, falls back to Playwright.
    """
    if agent_id in _active:
        await stop_screencast(agent_id)

    every_n = max(1, round(60 / settings.screenshot_capture_fps))

    if await _start_via_browser_use(agent_id, browser_session, every_n):
        return
    if await _start_via_playwright(agent_id, page, every_n):
        return

    logger.warning("CDP screencast failed for %s — no frames will stream", agent_id)


async def stop_screencast(agent_id: str) -> None:
    """Stop the CDP screencast and clean up."""
    info = _active.pop(agent_id, None)
    if info is not None:
        try:
            if info["type"] == "playwright":
                await info["cdp"].send("Page.stopScreencast")
                await info["cdp"].detach()
            elif info["type"] == "browser_use":
                await info["cdp_client"].send_raw(
                    "Page.stopScreencast", session_id=info["session_id"]
                )
                info["cdp_client"]._event_registry.unregister("Page.screencastFrame")
        except Exception as exc:
            logger.debug("CDP teardown for %s: %s", agent_id, exc)
    frame_store.pop(agent_id, None)
    logger.info("CDP screencast stopped for %s", agent_id)


# ── Delivery Helpers ──────────────────────────────────────────────────────────


def get_frame_for_delivery(agent_id: str) -> bytes | None:
    """Return the latest JPEG bytes for this agent, or None."""
    frame = frame_store.get(agent_id)
    return frame.jpeg if frame is not None else None


def get_all_agent_ids() -> list[str]:
    """Return all agent IDs that currently have frames."""
    return list(frame_store.keys())
