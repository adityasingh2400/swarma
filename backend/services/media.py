from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Frame cache (keyed by video content hash) ────────────────────────────────
# Same pattern as the Gemini upload cache: identical video content → same frames
_frame_cache: dict[str, list[str]] = {}
_frame_locks: dict[str, asyncio.Lock] = {}
_frame_global_lock = asyncio.Lock()

_VIDEO_EXTENSIONS = {".mov", ".mp4", ".avi", ".mkv", ".webm", ".m4v", ".3gp"}


def preload_frame_cache(content_hash: str, frame_paths: list[str]) -> None:
    """Pre-populate the frame cache from a snapshot. Called by snapshot loader."""
    _frame_cache[content_hash] = frame_paths


def _video_content_hash(path: str) -> str:
    """Fast MD5 of first+last 2MB — fingerprints identical videos regardless of filename."""
    h = hashlib.md5()
    size = Path(path).stat().st_size
    chunk = 2 * 1024 * 1024
    with open(path, "rb") as f:
        h.update(f.read(chunk))
        if size > chunk * 2:
            f.seek(-chunk, 2)
            h.update(f.read(chunk))
    return h.hexdigest()


class MediaService:
    async def extract_frames(
        self,
        video_path: str,
        output_dir: str | None = None,
        interval_sec: float = 2.0,
    ) -> list[str]:
        # ── Cache lookup by content hash ──────────────────────────────────
        content_hash = await asyncio.to_thread(_video_content_hash, video_path)

        if content_hash in _frame_cache:
            cached = _frame_cache[content_hash]
            if cached and all(Path(p).exists() for p in cached):
                print(f"[FRAMES] Cache hit: {len(cached)} frames "
                      f"(hash: {content_hash[:8]}…)")
                return cached

        # ── Lock per content hash (prevents duplicate ffmpeg runs) ────────
        async with _frame_global_lock:
            if content_hash not in _frame_locks:
                _frame_locks[content_hash] = asyncio.Lock()
            lock = _frame_locks[content_hash]

        async with lock:
            # Double-check after acquiring lock (pre-extraction may have finished)
            if content_hash in _frame_cache:
                cached = _frame_cache[content_hash]
                if cached and all(Path(p).exists() for p in cached):
                    print(f"[FRAMES] Cache hit (after wait): {len(cached)} frames "
                          f"(hash: {content_hash[:8]}…)")
                    return cached

            # ── Run ffmpeg ────────────────────────────────────────────────
            out = Path(output_dir or settings.frames_dir)
            out.mkdir(parents=True, exist_ok=True)
            prefix = uuid.uuid4().hex[:8]
            pattern = str(out / f"{prefix}_%04d.jpg")

            # Optimizations vs the old command:
            #  -hwaccel auto     → use VideoToolbox (macOS) for HEVC decode
            #  scale=1280:-2     → 4K→720p before JPEG encode (6x fewer pixels)
            #  -q:v 5            → slightly lower quality, much faster encode
            #  -threads 4        → cap threads to avoid starving Gemini tasks
            cmd = [
                "ffmpeg",
                "-hwaccel", "auto",
                "-i", video_path,
                "-vf", f"scale=1280:-2,fps=1/{interval_sec}",
                "-q:v", "5",
                "-threads", "4",
                pattern,
                "-y", "-loglevel", "error",
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()

                if proc.returncode != 0:
                    logger.error("ffmpeg frame extraction failed: %s", stderr.decode())
                    if settings.demo_mode:
                        return self._generate_placeholder_frames(out, prefix)
                    return []

                frames = sorted(out.glob(f"{prefix}_*.jpg"))
                result = [str(f) for f in frames]

                # Store in cache
                if result:
                    _frame_cache[content_hash] = result
                    print(f"[FRAMES] Extracted and cached {len(result)} frames "
                          f"(hash: {content_hash[:8]}…)")

                return result

            except FileNotFoundError:
                logger.error("ffmpeg not found on PATH")
                if settings.demo_mode:
                    return self._generate_placeholder_frames(out, prefix)
                return []

    @classmethod
    async def preextract_demo_frames(cls) -> None:
        """Pre-extract frames from the demo video at startup so pipeline runs
        get an instant cache hit (0.0s) instead of waiting 33-63s for ffmpeg."""
        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)

        candidates = sorted(
            upload_dir.glob("*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        video = next(
            (c for c in candidates if c.suffix.lower() in _VIDEO_EXTENSIONS),
            None,
        )
        if not video:
            fallback = Path("test.MOV")
            if fallback.exists():
                video = fallback
            else:
                print("[FRAMES] ⚠ No demo video found — skipping pre-extraction")
                return

        import time as _t

        t0 = _t.time()
        size_mb = video.stat().st_size / 1024 / 1024
        print(f"[FRAMES] ═══ Pre-extracting frames: {video.name} ({size_mb:.0f}MB) ═══")

        svc = cls()
        frames = await svc.extract_frames(str(video))
        elapsed = _t.time() - t0
        print(f"[FRAMES] ═══ Pre-extraction complete: {len(frames)} frames "
              f"in {elapsed:.1f}s ═══", flush=True)

    async def extract_audio(self, video_path: str) -> str:
        out_dir = Path(settings.frames_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_path = str(out_dir / f"{uuid.uuid4().hex[:8]}_audio.wav")

        cmd = [
            "ffmpeg", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            audio_path,
            "-y", "-loglevel", "error",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("ffmpeg audio extraction failed: %s", stderr.decode())
                return ""
            return audio_path

        except FileNotFoundError:
            logger.error("ffmpeg not found on PATH")
            return ""

    async def extract_transcript(self, video_path: str) -> str:
        if settings.demo_mode:
            return (
                "So I've got a few things to sell today. First up, these AirPods Pro — "
                "barely used, just some minor scratches on the case. Next, my Sony "
                "WH-1000XM4 headphones — the headband has a crack and the battery "
                "drains pretty fast now. And finally this mechanical keyboard with "
                "its original cable, basically brand new condition."
            )
        # Use Gemini for transcription (extract_audio only produces a file path, not text)
        from backend.services.gemini import GeminiService
        gemini = GeminiService()
        return await gemini.transcribe_from_video(video_path)

    async def get_video_metadata(self, video_path: str) -> dict:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("ffprobe failed: %s", stderr.decode())
                if settings.demo_mode:
                    return self._mock_metadata()
                return {}

            data = json.loads(stdout.decode())
            fmt = data.get("format", {})
            duration = float(fmt.get("duration", 0))

            video_stream = next(
                (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
                {},
            )

            fps_str = video_stream.get("r_frame_rate", "0/1")
            parts = fps_str.split("/")
            fps = float(parts[0]) / float(parts[1]) if len(parts) == 2 and float(parts[1]) else 0.0

            return {
                "duration": duration,
                "width": video_stream.get("width", 0),
                "height": video_stream.get("height", 0),
                "fps": round(fps, 2),
                "codec": video_stream.get("codec_name", ""),
                "size_bytes": int(fmt.get("size", 0)),
            }

        except FileNotFoundError:
            logger.error("ffprobe not found on PATH")
            if settings.demo_mode:
                return self._mock_metadata()
            return {}

    def _generate_placeholder_frames(self, output_dir: Path, prefix: str) -> list[str]:
        frames: list[str] = []
        colors = [(52, 152, 219), (46, 204, 113), (231, 76, 60)]
        labels = ["Item Overview", "Close-up Detail", "Condition Check"]

        try:
            from PIL import Image, ImageDraw

            for i, (color, label) in enumerate(zip(colors, labels), 1):
                img = Image.new("RGB", (640, 480), color)
                draw = ImageDraw.Draw(img)
                bbox = draw.textbbox((0, 0), label)
                text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text(
                    ((640 - text_w) / 2, (480 - text_h) / 2),
                    label,
                    fill=(255, 255, 255),
                )
                path = output_dir / f"{prefix}_{i:04d}.jpg"
                img.save(str(path), "JPEG")
                frames.append(str(path))
        except ImportError:
            logger.warning("Pillow not installed; creating minimal placeholder files")
            for i in range(1, 4):
                path = output_dir / f"{prefix}_{i:04d}.jpg"
                path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9")
                frames.append(str(path))

        logger.info("Generated %d placeholder frames (demo mode)", len(frames))
        return frames

    @staticmethod
    def _mock_metadata() -> dict:
        return {
            "duration": 45.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "codec": "h264",
            "size_bytes": 15_000_000,
        }
