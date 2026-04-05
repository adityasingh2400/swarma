"""CDP screencast capture + binary WebSocket framing.

Uses Chrome DevTools Protocol (CDP) Page.screencastFrame events for async
video broadcast — no polling. Each agent gets its own CDP session when its
browser page is ready; the browser pushes JPEG frames directly to the handler.

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
from io import BytesIO

from PIL import Image

from backend.config import settings

logger = logging.getLogger("reroute.streaming")


# ── Frame Store ───────────────────────────────────────────────────────────────
# Latest frame always wins. No stale accumulation.
# CDP callback writes; server.py reads.


@dataclass(slots=True)
class FrameData:
    grid: bytes   # 320x240 JPEG q60 ~20 KB
    focus: bytes  # 1280x960 JPEG q80 ~100 KB
    ts: float     # time.time() when captured


frame_store: dict[str, FrameData] = {}

# Tracks which agent is currently focused (higher FPS delivery).
# Set by server.py when it receives focus:request / focus:release.
focused_agent_id: str | None = None

# Active CDP sessions — kept so stop_screencast can tear them down.
_cdp_sessions: dict[str, object] = {}


# ── JPEG Encoding (runs in thread pool) ───────────────────────────────────────


def _encode_frame(jpeg_bytes: bytes) -> tuple[bytes, bytes]:
    """Decode an incoming CDP JPEG frame, produce grid + focus variants.

    Runs in a thread-pool executor to avoid blocking the event loop.
    Returns (grid_jpeg, focus_jpeg).
    """
    img = Image.open(BytesIO(jpeg_bytes))

    focus_img = img.resize(
        (settings.screenshot_focus_width, settings.screenshot_focus_height),
        Image.LANCZOS,
    )
    focus_buf = BytesIO()
    focus_img.save(focus_buf, format="JPEG", quality=settings.screenshot_focus_quality)
    focus_jpeg = focus_buf.getvalue()

    grid_img = img.resize(
        (settings.screenshot_grid_width, settings.screenshot_grid_height),
        Image.LANCZOS,
    )
    grid_buf = BytesIO()
    grid_img.save(grid_buf, format="JPEG", quality=settings.screenshot_grid_quality)
    grid_jpeg = grid_buf.getvalue()

    return grid_jpeg, focus_jpeg


# ── Binary Frame Encoding ─────────────────────────────────────────────────────


def encode_binary_frame(agent_id: str, jpeg_bytes: bytes) -> bytes:
    """Encode a JPEG into the binary WS frame format.

    Format: [0x01][32-byte utf8 agentId null-padded][4-byte uint32 BE timestamp][JPEG]
    """
    version = b"\x01"
    agent_bytes = agent_id.encode("utf-8")[:32].ljust(32, b"\x00")
    ts = struct.pack(">I", int(time.time()) & 0xFFFFFFFF)
    return version + agent_bytes + ts + jpeg_bytes


# ── CDP Screencast ────────────────────────────────────────────────────────────


async def start_screencast(agent_id: str, page) -> None:
    """Start a CDP screencast session for one agent's Playwright Page.

    The browser pushes JPEG frames via Page.screencastFrame events
    asynchronously — no polling loop needed.

    Args:
        agent_id: Unique agent identifier (e.g. "ebay-research-0").
        page:     Playwright Page from Browser-Use's browser context.

    Called by Person 1's orchestrator immediately after the agent's browser
    page is ready.
    """
    if agent_id in _cdp_sessions:
        logger.warning("start_screencast called twice for %s — stopping old session", agent_id)
        await stop_screencast(agent_id)

    cdp = await page.context.new_cdp_session(page)
    _cdp_sessions[agent_id] = cdp

    # everyNthFrame: deliver 1 out of every N frames from the browser's vsync (~60 Hz).
    # screenshot_capture_fps=2 → everyNthFrame=30; fps=4 → 15; fps=1 → 60; etc.
    vsync_hz = 60
    every_n = max(1, round(vsync_hz / settings.screenshot_capture_fps))

    await cdp.send("Page.startScreencast", {
        "format": "jpeg",
        "quality": settings.screenshot_focus_quality,
        "maxWidth": settings.screenshot_focus_width,
        "maxHeight": settings.screenshot_focus_height,
        "everyNthFrame": every_n,
    })

    loop = asyncio.get_running_loop()

    async def _on_frame(params: dict) -> None:
        session_id = params["sessionId"]
        # ACK immediately — browser pauses delivery until we ACK.
        try:
            await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception:
            pass  # session may already be torn down

        jpeg_bytes = base64.b64decode(params["data"])
        try:
            grid, focus = await loop.run_in_executor(None, _encode_frame, jpeg_bytes)
            frame_store[agent_id] = FrameData(grid=grid, focus=focus, ts=time.time())
        except Exception as exc:
            logger.warning("Frame encode failed for %s: %s", agent_id, exc)

    cdp.on("Page.screencastFrame", _on_frame)
    logger.info(
        "CDP screencast started for %s (everyNthFrame=%d, ~%.1f fps)",
        agent_id, every_n, vsync_hz / every_n,
    )


async def stop_screencast(agent_id: str) -> None:
    """Stop the CDP screencast session and remove the agent's frames.

    Called by Person 1's orchestrator when an agent completes or is cancelled.
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


def get_frame_for_delivery(agent_id: str) -> tuple[bytes, bool] | None:
    """Return (jpeg_bytes, is_focus) for the latest frame, or None."""
    frame = frame_store.get(agent_id)
    if frame is None:
        return None
    if agent_id == focused_agent_id:
        return frame.focus, True
    return frame.grid, False


def get_all_agent_ids() -> list[str]:
    """Return all agent IDs that currently have frames in the store."""
    return list(frame_store.keys())
