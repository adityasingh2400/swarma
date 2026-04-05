"""Tests for backend/streaming.py — binary frame encoding, JPEG encoding, frame store."""
from __future__ import annotations

import asyncio
import base64
import struct
import time
from io import BytesIO
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from PIL import Image

from backend.config import settings
from backend.streaming import (
    FrameData,
    _encode_frame,
    encode_binary_frame,
    frame_store,
    get_all_agent_ids,
    get_frame_for_delivery,
    start_screencast,
    stop_screencast,
)
import backend.streaming as streaming_mod


def _make_jpeg(width: int = 1920, height: int = 1080, color=(100, 150, 200)) -> bytes:
    """Create a minimal JPEG for use as a synthetic CDP frame."""
    img = Image.new("RGB", (width, height), color=color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


# ── Binary Frame Protocol ────────────────────────────────────────────────────


class TestBinaryFrameEncoding:
    """Binary WS frame: [0x01][32-byte agentId][4-byte uint32 BE ts][JPEG]"""

    def test_header_total_37_bytes(self, sample_jpeg_bytes):
        frame = encode_binary_frame("agent-1", sample_jpeg_bytes)
        header = frame[:37]
        payload = frame[37:]
        assert len(header) == 37
        assert payload == sample_jpeg_bytes

    def test_version_byte_is_0x01(self, sample_jpeg_bytes):
        frame = encode_binary_frame("agent-1", sample_jpeg_bytes)
        assert frame[0:1] == b"\x01"

    def test_agent_id_null_padded_to_32(self, sample_jpeg_bytes):
        frame = encode_binary_frame("abc", sample_jpeg_bytes)
        agent_field = frame[1:33]
        assert len(agent_field) == 32
        assert agent_field[:3] == b"abc"
        assert agent_field[3:] == b"\x00" * 29

    def test_agent_id_truncated_at_32(self, sample_jpeg_bytes):
        long_id = "a" * 50
        frame = encode_binary_frame(long_id, sample_jpeg_bytes)
        agent_field = frame[1:33]
        assert len(agent_field) == 32
        assert agent_field == (b"a" * 32)

    def test_timestamp_is_uint32_big_endian(self, sample_jpeg_bytes):
        before = int(time.time())
        frame = encode_binary_frame("x", sample_jpeg_bytes)
        after = int(time.time())

        ts_bytes = frame[33:37]
        ts = struct.unpack(">I", ts_bytes)[0]
        assert before <= ts <= after

    def test_jpeg_payload_preserved(self, sample_jpeg_bytes):
        frame = encode_binary_frame("agent-1", sample_jpeg_bytes)
        assert frame[37:] == sample_jpeg_bytes

    def test_empty_jpeg(self):
        frame = encode_binary_frame("agent-1", b"")
        assert len(frame) == 37
        assert frame[37:] == b""


# ── JPEG Encoding ────────────────────────────────────────────────────────────


class TestJpegEncoding:
    """_encode_frame takes an incoming CDP JPEG and returns grid + focus variants."""

    def test_produces_grid_and_focus(self):
        jpeg = _make_jpeg()
        grid, focus = _encode_frame(jpeg)
        assert isinstance(grid, bytes) and len(grid) > 0
        assert isinstance(focus, bytes) and len(focus) > 0
        # Focus is higher quality + larger resolution → bigger
        assert len(focus) > len(grid)

    def test_grid_dimensions(self):
        grid, _ = _encode_frame(_make_jpeg())
        decoded = Image.open(BytesIO(grid))
        assert decoded.size == (320, 240)

    def test_focus_dimensions(self):
        _, focus = _encode_frame(_make_jpeg())
        decoded = Image.open(BytesIO(focus))
        assert decoded.size == (1280, 960)


# ── Frame Store ──────────────────────────────────────────────────────────────


class TestFrameStore:
    def setup_method(self):
        frame_store.clear()
        streaming_mod.focused_agent_id = None

    def test_get_frame_returns_none_when_empty(self):
        assert get_frame_for_delivery("nonexistent") is None

    def test_get_frame_returns_grid_by_default(self):
        frame_store["agent-1"] = FrameData(grid=b"GRID", focus=b"FOCUS", ts=1.0)
        result = get_frame_for_delivery("agent-1")
        assert result == (b"GRID", False)

    def test_get_frame_returns_focus_when_focused(self):
        frame_store["agent-1"] = FrameData(grid=b"GRID", focus=b"FOCUS", ts=1.0)
        streaming_mod.focused_agent_id = "agent-1"
        result = get_frame_for_delivery("agent-1")
        assert result == (b"FOCUS", True)

    def test_get_all_agent_ids(self):
        frame_store["a"] = FrameData(grid=b"", focus=b"", ts=1.0)
        frame_store["b"] = FrameData(grid=b"", focus=b"", ts=1.0)
        ids = get_all_agent_ids()
        assert set(ids) == {"a", "b"}

    def test_latest_frame_wins(self):
        frame_store["agent-1"] = FrameData(grid=b"OLD", focus=b"", ts=1.0)
        frame_store["agent-1"] = FrameData(grid=b"NEW", focus=b"", ts=2.0)
        result = get_frame_for_delivery("agent-1")
        assert result == (b"NEW", False)


# ── Frame Store (extended) ───────────────────────────────────────────────────


class TestFrameStoreExtended:
    def setup_method(self):
        frame_store.clear()
        streaming_mod.focused_agent_id = None

    def test_non_focused_agent_returns_grid_when_other_is_focused(self):
        frame_store["agent-1"] = FrameData(grid=b"G1", focus=b"F1", ts=1.0)
        frame_store["agent-2"] = FrameData(grid=b"G2", focus=b"F2", ts=1.0)
        streaming_mod.focused_agent_id = "agent-1"
        assert get_frame_for_delivery("agent-2") == (b"G2", False)

    def test_focus_mode_switch(self):
        frame_store["agent-1"] = FrameData(grid=b"G", focus=b"F", ts=1.0)
        streaming_mod.focused_agent_id = "agent-1"
        assert get_frame_for_delivery("agent-1") == (b"F", True)
        streaming_mod.focused_agent_id = None
        assert get_frame_for_delivery("agent-1") == (b"G", False)

    def test_get_all_agent_ids_empty(self):
        assert get_all_agent_ids() == []

    def test_get_all_agent_ids_order_stable(self):
        for key in ("z", "a", "m"):
            frame_store[key] = FrameData(grid=b"", focus=b"", ts=1.0)
        ids = get_all_agent_ids()
        assert set(ids) == {"z", "a", "m"}


# ── stop_screencast ───────────────────────────────────────────────────────────


class TestStopScreencast:
    def setup_method(self):
        frame_store.clear()
        streaming_mod._cdp_sessions.clear()

    @pytest.mark.anyio
    async def test_removes_frame_store_entry(self):
        frame_store["agent-1"] = FrameData(grid=b"G", focus=b"F", ts=1.0)
        await stop_screencast("agent-1")
        assert "agent-1" not in frame_store

    @pytest.mark.anyio
    async def test_noop_for_unknown_agent(self):
        await stop_screencast("nonexistent")  # should not raise

    @pytest.mark.anyio
    async def test_sends_stop_screencast_command(self):
        mock_cdp = AsyncMock()
        streaming_mod._cdp_sessions["agent-1"] = mock_cdp
        await stop_screencast("agent-1")
        mock_cdp.send.assert_called_once_with("Page.stopScreencast")

    @pytest.mark.anyio
    async def test_detaches_cdp_session(self):
        mock_cdp = AsyncMock()
        streaming_mod._cdp_sessions["agent-1"] = mock_cdp
        await stop_screencast("agent-1")
        mock_cdp.detach.assert_called_once()

    @pytest.mark.anyio
    async def test_removes_cdp_session_from_registry(self):
        mock_cdp = AsyncMock()
        streaming_mod._cdp_sessions["agent-1"] = mock_cdp
        await stop_screencast("agent-1")
        assert "agent-1" not in streaming_mod._cdp_sessions

    @pytest.mark.anyio
    async def test_cdp_send_exception_is_swallowed(self):
        """CDP errors during teardown should not propagate (browser may already be gone)."""
        mock_cdp = AsyncMock()
        mock_cdp.send.side_effect = Exception("CDP session closed")
        streaming_mod._cdp_sessions["agent-1"] = mock_cdp
        frame_store["agent-1"] = FrameData(grid=b"G", focus=b"F", ts=1.0)
        await stop_screencast("agent-1")  # must not raise
        assert "agent-1" not in frame_store

    @pytest.mark.anyio
    async def test_cdp_detach_exception_is_swallowed(self):
        mock_cdp = AsyncMock()
        mock_cdp.detach.side_effect = Exception("already detached")
        streaming_mod._cdp_sessions["agent-1"] = mock_cdp
        await stop_screencast("agent-1")  # must not raise


# ── start_screencast ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_cdp():
    cdp = AsyncMock()
    cdp.on = MagicMock()
    return cdp


@pytest.fixture
def mock_page(mock_cdp):
    page = AsyncMock()
    page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)
    return page


class TestStartScreencast:
    def setup_method(self):
        frame_store.clear()
        streaming_mod._cdp_sessions.clear()
        streaming_mod.focused_agent_id = None

    @pytest.mark.anyio
    async def test_registers_agent_in_cdp_sessions(self, mock_page, mock_cdp):
        await start_screencast("agent-1", mock_page)
        assert "agent-1" in streaming_mod._cdp_sessions

    @pytest.mark.anyio
    async def test_sends_start_screencast_command(self, mock_page, mock_cdp):
        await start_screencast("agent-1", mock_page)
        first_call = mock_cdp.send.call_args_list[0]
        assert first_call[0][0] == "Page.startScreencast"

    @pytest.mark.anyio
    async def test_screencast_format_is_jpeg(self, mock_page, mock_cdp):
        await start_screencast("agent-1", mock_page)
        params = mock_cdp.send.call_args_list[0][0][1]
        assert params["format"] == "jpeg"

    @pytest.mark.anyio
    async def test_screencast_quality_from_settings(self, mock_page, mock_cdp):
        await start_screencast("agent-1", mock_page)
        params = mock_cdp.send.call_args_list[0][0][1]
        assert params["quality"] == settings.screenshot_focus_quality

    @pytest.mark.anyio
    async def test_screencast_dimensions_from_settings(self, mock_page, mock_cdp):
        await start_screencast("agent-1", mock_page)
        params = mock_cdp.send.call_args_list[0][0][1]
        assert params["maxWidth"] == settings.screenshot_focus_width
        assert params["maxHeight"] == settings.screenshot_focus_height

    @pytest.mark.anyio
    async def test_every_n_frame_calculation(self, mock_page, mock_cdp):
        # Default fps=2.0 → everyNthFrame=30 (60 Hz / 2)
        await start_screencast("agent-1", mock_page)
        params = mock_cdp.send.call_args_list[0][0][1]
        expected = max(1, round(60 / settings.screenshot_capture_fps))
        assert params["everyNthFrame"] == expected

    @pytest.mark.anyio
    async def test_registers_screencast_frame_handler(self, mock_page, mock_cdp):
        await start_screencast("agent-1", mock_page)
        mock_cdp.on.assert_called_once_with("Page.screencastFrame", ANY)

    @pytest.mark.anyio
    async def test_duplicate_start_stops_old_session(self, mock_page, mock_cdp):
        await start_screencast("agent-1", mock_page)
        await start_screencast("agent-1", mock_page)
        stop_calls = [
            c for c in mock_cdp.send.call_args_list if c[0][0] == "Page.stopScreencast"
        ]
        assert len(stop_calls) >= 1

    @pytest.mark.anyio
    async def test_frame_handler_populates_frame_store(self, mock_page, mock_cdp, sample_jpeg_bytes):
        """Frame event → decode JPEG → store grid+focus variants."""
        captured: dict = {}
        mock_cdp.on.side_effect = lambda event, fn: captured.update({event: fn})

        await start_screencast("agent-1", mock_page)
        handler = captured["Page.screencastFrame"]

        await handler({
            "sessionId": 42,
            "data": base64.b64encode(sample_jpeg_bytes).decode(),
        })

        assert "agent-1" in frame_store
        assert len(frame_store["agent-1"].grid) > 0
        assert len(frame_store["agent-1"].focus) > 0

    @pytest.mark.anyio
    async def test_frame_handler_acks_session(self, mock_page, mock_cdp, sample_jpeg_bytes):
        """Handler must ACK every frame so the browser continues pushing."""
        captured: dict = {}
        mock_cdp.on.side_effect = lambda event, fn: captured.update({event: fn})

        await start_screencast("agent-1", mock_page)
        handler = captured["Page.screencastFrame"]
        await handler({
            "sessionId": 99,
            "data": base64.b64encode(sample_jpeg_bytes).decode(),
        })

        ack_calls = [
            c for c in mock_cdp.send.call_args_list
            if c[0][0] == "Page.screencastFrameAck"
        ]
        assert len(ack_calls) == 1
        assert ack_calls[0][0][1] == {"sessionId": 99}

    @pytest.mark.anyio
    async def test_frame_handler_bad_jpeg_does_not_crash(self, mock_page, mock_cdp):
        """Corrupt JPEG must be logged and dropped — handler must not raise."""
        captured: dict = {}
        mock_cdp.on.side_effect = lambda event, fn: captured.update({event: fn})

        await start_screencast("agent-1", mock_page)
        handler = captured["Page.screencastFrame"]
        bad_data = base64.b64encode(b"not a jpeg at all").decode()
        await handler({"sessionId": 1, "data": bad_data})  # must not raise
        assert "agent-1" not in frame_store

    @pytest.mark.anyio
    async def test_frame_handler_updates_timestamp(self, mock_page, mock_cdp, sample_jpeg_bytes):
        captured: dict = {}
        mock_cdp.on.side_effect = lambda event, fn: captured.update({event: fn})

        before = time.time()
        await start_screencast("agent-1", mock_page)
        handler = captured["Page.screencastFrame"]
        await handler({
            "sessionId": 1,
            "data": base64.b64encode(sample_jpeg_bytes).decode(),
        })
        after = time.time()

        assert "agent-1" in frame_store
        assert before <= frame_store["agent-1"].ts <= after
