"""Shared fixtures for the Person 3 test suite."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Resolve the test video path once
_UPLOADS = Path(__file__).resolve().parent.parent / "data" / "uploads"
_TEST_VIDEOS = sorted(_UPLOADS.glob("*.mp4"))

TEST_VIDEO_PATH = str(_TEST_VIDEOS[0]) if _TEST_VIDEOS else None


@pytest.fixture
def test_video() -> str:
    """Path to the test video in data/uploads/. Skips if missing."""
    if TEST_VIDEO_PATH is None:
        pytest.skip("No test video found in data/uploads/")
    return TEST_VIDEO_PATH


@pytest.fixture
def sample_jpeg_bytes() -> bytes:
    """A minimal valid JPEG (1x1 red pixel) for unit tests."""
    import struct
    # Minimal JPEG: SOI + APP0 + DQT + SOF0 + DHT + SOS + data + EOI
    # Easier: use Pillow to generate a tiny one
    from io import BytesIO
    from PIL import Image

    img = Image.new("RGB", (64, 64), color=(200, 50, 50))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


@pytest.fixture
def make_jpeg():
    """Factory fixture: make_jpeg(width, height, color) -> bytes."""
    from io import BytesIO
    from PIL import Image

    def _make(w: int = 64, h: int = 64, color: tuple = (128, 128, 128)) -> bytes:
        img = Image.new("RGB", (w, h), color=color)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()

    return _make
