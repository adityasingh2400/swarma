"""CDP screencast capture + binary WebSocket framing.

Uses Chrome DevTools Protocol (CDP) Page.screencastFrame events for async
video broadcast — no polling. Each agent gets its own CDP session when its
browser page is ready; the browser pushes JPEG frames directly to the handler.

CDP scales frames to 320×240 before encoding — no server-side PIL processing.
The frame handler is a pure store: decode base64, write to frame_store.

Binary frame format (confirmed with Person 4):
  [0x01] [32-byte utf8 agentId null-padded] [4-byte uint32 BE timestamp] [JPEG bytes]
  Header total: 37 bytes.

Person 1 hook points — call these from the real orchestrator:
  await streaming.start_screencast(agent_id, page)  # on browser page ready
  await streaming.stop_screencast(agent_id)          # on agent done / cancelled
"""
from __future__ import annotations

import asyncio
import base64
import logging
import struct
import time
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger("reroute.streaming")


# ── Frame Store ───────────────────────────────────────────────────────────────
# Latest frame always wins. No stale accumulation.
# CDP callback writes; server.py reads.


@dataclass(slots=True)
class FrameData:
    jpeg: bytes  # 320×240 JPEG q60, pre-scaled by CDP — no server-side resize
    ts: float    # time.time() when received


frame_store: dict[str, FrameData] = {}

# Active CDP sessions — kept so stop_screencast can tear them down.
_cdp_sessions: dict[str, object] = {}


# ── Binary Frame Encoding ─────────────────────────────────────────────────────


def encode_binary_frame(agent_id: str, jpeg_bytes: bytes) -> bytes:
    """Pack a JPEG into the confirmed binary WS frame format.

    Format: [0x01][32-byte utf8 agentId null-padded][4-byte uint32 BE timestamp][JPEG]
    """
    agent_bytes = agent_id.encode("utf-8")[:32].ljust(32, b"\x00")
    ts = struct.pack(">I", int(time.time()) & 0xFFFFFFFF)
    return b"\x01" + agent_bytes + ts + jpeg_bytes


# ── CDP Screencast ────────────────────────────────────────────────────────────


async def start_screencast(agent_id: str, page) -> None:
    """Start a CDP screencast session for one agent's Playwright Page.

    The browser pushes JPEG frames via Page.screencastFrame events.
    CDP performs the resize to the configured grid dimensions before encoding —
    no server-side image processing.

    Args:
        agent_id: Unique agent identifier (e.g. "ebay-research-0").
        page:     Playwright Page from Browser-Use's browser_session.

    Called by the orchestrator immediately after the agent's browser page is ready.
    """
    if agent_id in _cdp_sessions:
        logger.warning("start_screencast called twice for %s — stopping old session", agent_id)
        await stop_screencast(agent_id)

    try:
        ctx = getattr(page, 'context', None)
        if ctx is None and hasattr(page, '_impl_obj'):
            ctx = page._impl_obj.context
        if ctx is None:
            raise AttributeError("Cannot access browser context from page object")
        cdp = await ctx.new_cdp_session(page)
    except Exception as exc:
        logger.warning("CDP session creation failed for %s: %s — falling back to screenshot callbacks", agent_id, exc)
        return
    _cdp_sessions[agent_id] = cdp

    # everyNthFrame: 1 out of every N frames from the browser's vsync (~60 Hz).
    # fps=2 → everyNthFrame=30; fps=5 → 12; fps=1 → 60.
    every_n = max(1, round(60 / settings.screenshot_capture_fps))

    await cdp.send("Page.startScreencast", {
        "format": "jpeg",
        "quality": settings.screenshot_grid_quality,     # 60
        "maxWidth": settings.screenshot_grid_width,      # 320
        "maxHeight": settings.screenshot_grid_height,    # 240
        "everyNthFrame": every_n,
    })

    async def _on_frame_async(params: dict) -> None:
        session_id = params["sessionId"]
        try:
            await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception as exc:
            logger.debug("screencastFrameAck failed for %s (session likely torn down): %s", agent_id, exc)
        jpeg_bytes = base64.b64decode(params["data"])
        frame_store[agent_id] = FrameData(jpeg=jpeg_bytes, ts=time.time())

    def _on_frame(params: dict) -> None:
        """Sync wrapper — Playwright's cdp.on() dispatches synchronously."""
        asyncio.ensure_future(_on_frame_async(params))

    cdp.on("Page.screencastFrame", _on_frame)
    logger.info(
        "CDP screencast started for %s (everyNthFrame=%d, ~%.1f fps)",
        agent_id, every_n, 60 / every_n,
    )


async def stop_screencast(agent_id: str) -> None:
    """Stop the CDP screencast session and remove the agent's frames.

    Called by the orchestrator when an agent completes or is cancelled.
    """
    cdp = _cdp_sessions.pop(agent_id, None)
    if cdp is not None:
        try:
            await cdp.send("Page.stopScreencast")
            await cdp.detach()
        except Exception as exc:
            logger.debug("CDP teardown for %s: %s", agent_id, exc)
    frame_store.pop(agent_id, None)
    logger.info("CDP screencast stopped for %s", agent_id)


# ── Delivery Helpers (used by server.py WS screenshot endpoint) ───────────────


def get_frame_for_delivery(agent_id: str) -> bytes | None:
    """Return the latest JPEG bytes for this agent, or None if no frame yet."""
    frame = frame_store.get(agent_id)
    return frame.jpeg if frame is not None else None


def get_all_agent_ids() -> list[str]:
    """Return all agent IDs that currently have frames in the store."""
    return list(frame_store.keys())
