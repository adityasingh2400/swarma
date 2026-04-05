"""Tests for backend/streaming.py — binary frame encoding, JPEG encoding, frame store."""
from __future__ import annotations

import struct
import time

import pytest

from backend.streaming import (
    FrameData,
    _encode_and_resize,
    encode_binary_frame,
    frame_store,
    get_all_agent_ids,
    get_frame_for_delivery,
    stop_capture,
)
import backend.streaming as streaming_mod


# ── Binary Frame Protocol ────────────────────────────────────────────────────


class TestBinaryFrameEncoding:
    """Binary WS frame: [0x01][32-byte agentId][4-byte uint32 BE ts][JPEG]"""

    def test_header_total_37_bytes(self, sample_jpeg_bytes):
        frame = encode_binary_frame("agent-1", sample_jpeg_bytes)
        header = frame[: 37]
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
    def test_produces_grid_and_focus(self, sample_jpeg_bytes):
        # _encode_and_resize expects PNG input
        from io import BytesIO
        from PIL import Image

        img = Image.new("RGB", (1920, 1080), color=(100, 150, 200))
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        grid, focus = _encode_and_resize(png_bytes)
        assert isinstance(grid, bytes)
        assert isinstance(focus, bytes)
        assert len(grid) > 0
        assert len(focus) > 0
        # Focus should be larger (higher quality + resolution)
        assert len(focus) > len(grid)

    def test_grid_dimensions(self):
        from io import BytesIO
        from PIL import Image

        img = Image.new("RGB", (1920, 1080), color=(50, 50, 50))
        buf = BytesIO()
        img.save(buf, format="PNG")

        grid, _ = _encode_and_resize(buf.getvalue())
        decoded = Image.open(BytesIO(grid))
        assert decoded.size == (320, 240)

    def test_focus_dimensions(self):
        from io import BytesIO
        from PIL import Image

        img = Image.new("RGB", (1920, 1080), color=(50, 50, 50))
        buf = BytesIO()
        img.save(buf, format="PNG")

        _, focus = _encode_and_resize(buf.getvalue())
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

    def test_stop_capture_removes_agent(self):
        frame_store["agent-1"] = FrameData(grid=b"G", focus=b"F", ts=1.0)
        stop_capture("agent-1")
        assert "agent-1" not in frame_store

    def test_stop_capture_noop_for_unknown(self):
        stop_capture("nonexistent")  # should not raise

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
