"""Tests for intake.py ffmpeg operations — requires ffmpeg/ffprobe on PATH."""
from __future__ import annotations

import asyncio

import pytest

from backend.intake import (
    MAX_VIDEO_DURATION_SEC,
    _get_video_duration,
    _get_video_fps,
    _preprocess_video,
    _extract_segment_frames,
    extract_audio,
    extract_frames_streaming,
)


@pytest.fixture
def run(test_video):
    """Helper to run async functions."""
    def _run(coro):
        return asyncio.get_event_loop().run_until_complete(coro)
    return _run


# ── Duration / FPS Detection ─────────────────────────────────────────────────


class TestVideoDuration:
    def test_returns_positive_float(self, test_video):
        duration = asyncio.get_event_loop().run_until_complete(
            _get_video_duration(test_video)
        )
        assert isinstance(duration, float)
        assert duration > 0

    def test_test_video_under_60s(self, test_video):
        duration = asyncio.get_event_loop().run_until_complete(
            _get_video_duration(test_video)
        )
        assert duration <= MAX_VIDEO_DURATION_SEC, (
            f"Test video is {duration:.1f}s, exceeds {MAX_VIDEO_DURATION_SEC}s limit"
        )

    def test_raises_on_nonexistent_file(self):
        with pytest.raises(ValueError, match="ffprobe failed"):
            asyncio.get_event_loop().run_until_complete(
                _get_video_duration("/nonexistent/video.mp4")
            )


class TestVideoFps:
    def test_returns_positive_float(self, test_video):
        fps = asyncio.get_event_loop().run_until_complete(
            _get_video_fps(test_video)
        )
        assert isinstance(fps, float)
        assert fps > 0

    def test_test_video_is_30fps(self, test_video):
        fps = asyncio.get_event_loop().run_until_complete(
            _get_video_fps(test_video)
        )
        assert abs(fps - 30.0) < 1.0, f"Expected ~30fps, got {fps}"


# ── Preprocessing ────────────────────────────────────────────────────────────


class TestPreprocessVideo:
    def test_skips_transcode_for_h264_1080p(self, test_video):
        """Test video is h264 608x1080 — should skip transcode."""
        result = asyncio.get_event_loop().run_until_complete(
            _preprocess_video(test_video)
        )
        # Should return original path (no transcode needed)
        assert result == test_video


# ── Audio Extraction ─────────────────────────────────────────────────────────


class TestExtractAudio:
    def test_produces_wav_file(self, test_video):
        from pathlib import Path

        audio_path = asyncio.get_event_loop().run_until_complete(
            extract_audio(test_video)
        )
        try:
            p = Path(audio_path)
            assert p.exists()
            assert p.suffix == ".wav"
            assert p.stat().st_size > 0
        finally:
            Path(audio_path).unlink(missing_ok=True)

    def test_raises_on_nonexistent_video(self):
        with pytest.raises(ValueError, match="Audio extraction failed"):
            asyncio.get_event_loop().run_until_complete(
                extract_audio("/nonexistent/video.mp4")
            )


# ── Streaming Frame Extraction ───────────────────────────────────────────────


class TestExtractFramesStreaming:
    def test_yields_jpeg_frames(self, test_video):
        frames = []

        async def _collect():
            async for idx, data in extract_frames_streaming(test_video, fps=2.0):
                frames.append((idx, data))

        asyncio.get_event_loop().run_until_complete(_collect())
        assert len(frames) > 0
        # Each frame should be valid JPEG
        for idx, data in frames:
            assert data[:2] == b"\xff\xd8", f"Frame {idx} is not JPEG"
            assert data[-2:] == b"\xff\xd9", f"Frame {idx} missing JPEG EOI"

    def test_frame_count_proportional_to_duration_and_fps(self, test_video):
        frames = []

        async def _collect():
            async for idx, data in extract_frames_streaming(test_video, fps=1.0):
                frames.append((idx, data))

        asyncio.get_event_loop().run_until_complete(_collect())
        # ~34s video at 1fps should yield ~30-38 frames
        assert 20 <= len(frames) <= 45, f"Got {len(frames)} frames at 1fps"

    def test_frame_indices_sequential(self, test_video):
        indices = []

        async def _collect():
            async for idx, _ in extract_frames_streaming(test_video, fps=1.0):
                indices.append(idx)

        asyncio.get_event_loop().run_until_complete(_collect())
        assert indices == list(range(len(indices)))


# ── Segment Extraction ───────────────────────────────────────────────────────


class TestExtractSegmentFrames:
    def test_returns_correct_number_of_segments(self, test_video):
        segments = asyncio.get_event_loop().run_until_complete(
            _extract_segment_frames(test_video, num_segments=5)
        )
        assert len(segments) == 5

    def test_each_segment_has_frames(self, test_video):
        segments = asyncio.get_event_loop().run_until_complete(
            _extract_segment_frames(test_video, num_segments=5)
        )
        non_empty = [s for s in segments if len(s) > 0]
        # Most segments should have at least one frame
        assert len(non_empty) >= 3

    def test_segment_frames_are_valid_jpeg(self, test_video):
        segments = asyncio.get_event_loop().run_until_complete(
            _extract_segment_frames(test_video, num_segments=3)
        )
        for seg in segments:
            for idx, data in seg:
                assert data[:2] == b"\xff\xd8"
                assert data[-2:] == b"\xff\xd9"
