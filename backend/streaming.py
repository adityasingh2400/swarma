"""CDP screenshot capture + binary WebSocket framing.

Captures screenshots from Browser-Use agent browser contexts via CDP,
encodes them as JPEG at two quality levels (grid thumbnail + focus),
and stores them in a module-level ring buffer for the server to read.

Binary frame format (confirmed with Person 4):
  [0x01] [32-byte utf8 agentId null-padded] [4-byte uint32 BE timestamp] [JPEG bytes]
  Header total: 37 bytes.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image

from backend.config import settings

logger = logging.getLogger("reroute.streaming")

# ── Frame Store (module-level ring buffer) ────────────────────────────────────
# Latest frame always wins. No stale accumulation.
# Event loop thread owns writes; server.py reads.


@dataclass(slots=True)
class FrameData:
    grid: bytes  # 320x240 JPEG q60 ~20KB
    focus: bytes  # 1280x960 JPEG q80 ~100KB
    ts: float  # time.time() when captured


frame_store: dict[str, FrameData] = {}

# Tracks which agent is currently focused (higher FPS delivery).
# Set by server.py when it receives focus:request / focus:release.
focused_agent_id: str | None = None


# ── JPEG Encoding (runs in thread pool) ───────────────────────────────────────


def _encode_and_resize(png_bytes: bytes) -> tuple[bytes, bytes]:
    """Decode a PNG screenshot, produce grid + focus JPEG variants.

    This runs in a thread pool to avoid blocking the event loop.
    Returns (grid_jpeg, focus_jpeg).
    """
    img = Image.open(BytesIO(png_bytes))

    # Focus resolution
    focus_img = img.resize(
        (settings.screenshot_focus_width, settings.screenshot_focus_height),
        Image.LANCZOS,
    )
    focus_buf = BytesIO()
    focus_img.save(focus_buf, format="JPEG", quality=settings.screenshot_focus_quality)
    focus_jpeg = focus_buf.getvalue()

    # Grid thumbnail
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
    """Encode a screenshot into the binary WS frame format.

    Format: [0x01][32-byte utf8 agentId null-padded][4-byte uint32 BE timestamp][JPEG]
    """
    # Version byte
    version = b"\x01"

    # Agent ID: 32 bytes, utf8, null-padded
    agent_bytes = agent_id.encode("utf-8")[:32]
    agent_padded = agent_bytes.ljust(32, b"\x00")

    # Timestamp: uint32 big-endian (seconds since epoch, wraps ~2106)
    ts = struct.pack(">I", int(time.time()) & 0xFFFFFFFF)

    return version + agent_padded + ts + jpeg_bytes


# ── Screenshot Capture Loop ───────────────────────────────────────────────────


async def capture_loop(agent_id: str, get_page_fn):
    """Continuously capture CDP screenshots for one agent.

    Args:
        agent_id: Unique agent identifier (e.g. "ebay-research-0").
        get_page_fn: An async callable that returns a Playwright Page object
                     (or None if the agent's browser is not yet ready).
                     This is a callable rather than a direct Page reference
                     because the page may change during context recycling.

    The loop runs at settings.screenshot_capture_fps (default 2 fps).
    It writes to frame_store[agent_id] on every capture.
    The loop exits when cancelled (agent completes or is stopped).

    NOTE: get_page_fn is stubbed for now. The actual implementation depends
    on how Browser-Use exposes CDP access from its Browser object. Person 1
    will provide get_browser(agent_id) -> Browser, and we need to extract
    a Playwright Page from that. See TODO below.
    """
    interval = 1.0 / settings.screenshot_capture_fps
    logger.info("capture_loop started for %s (%.1f fps)", agent_id, settings.screenshot_capture_fps)

    try:
        while True:
            page = None
            try:
                page = await get_page_fn()
            except Exception:
                logger.debug("get_page_fn not ready for %s, retrying", agent_id)
                await asyncio.sleep(interval)
                continue

            if page is None:
                await asyncio.sleep(interval)
                continue

            try:
                # CDP screenshot returns PNG bytes
                png_bytes = await page.screenshot(type="png")

                # Offload JPEG encode + resize to thread pool
                grid_jpeg, focus_jpeg = await asyncio.to_thread(
                    _encode_and_resize, png_bytes
                )

                # Event loop thread writes to frame_store (no race condition)
                frame_store[agent_id] = FrameData(
                    grid=grid_jpeg,
                    focus=focus_jpeg,
                    ts=time.time(),
                )

            except Exception as exc:
                # Page may have been closed during context recycling
                logger.warning("Screenshot capture failed for %s: %s", agent_id, exc)

            await asyncio.sleep(interval)

    except asyncio.CancelledError:
        logger.info("capture_loop stopped for %s", agent_id)
        # Clean up frame store entry
        frame_store.pop(agent_id, None)
        raise


def stop_capture(agent_id: str) -> None:
    """Remove an agent's frame data from the store.

    Called when an agent completes or is recycled. The capture_loop task
    should be cancelled separately.
    """
    frame_store.pop(agent_id, None)


# ── Delivery Helpers (used by server.py WS screenshot endpoint) ───────────────


def get_frame_for_delivery(agent_id: str) -> tuple[bytes, bool] | None:
    """Get the latest frame for an agent, choosing grid or focus quality.

    Returns (jpeg_bytes, is_focus) or None if no frame available.
    """
    frame = frame_store.get(agent_id)
    if frame is None:
        return None

    if agent_id == focused_agent_id:
        return frame.focus, True
    return frame.grid, False


def get_all_agent_ids() -> list[str]:
    """Return all agent IDs that have frames in the store."""
    return list(frame_store.keys())
