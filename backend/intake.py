"""Video intake pipeline: streaming ffmpeg extraction + Gemini batch analysis.

Pipeline flow:
  1. ffmpeg extracts frames at 1 fps via streaming pipe (not batch)
  2. Frames are collected into batches of 3-5
  3. Each batch is sent to Gemini Flash-Lite for item detection (parallel fan-out)
  4. ItemCards are yielded as soon as any batch identifies items
  5. Best frames per item are extracted, cropped, resized for listing images

Uses the three-tier model split from gemini-pipeline-optimization.md:
  - Detection: Gemini 2.5 Flash-Lite (fast, cheap, classification-grade)
  - Detail:    Gemini 2.5 Flash (smarter, for title/description/pricing)
  - Agents:    ChatBrowserUse (separate rate limits, browser-optimized)
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image

from backend.config import settings
from backend.models.item_card import ItemCard, ItemCategory, DefectSignal

logger = logging.getLogger("reroute.intake")

# ── Analysis Prompt (padded to >=1024 tokens for Gemini context caching) ──────

DETECTION_PROMPT = """You are analyzing video frames of items someone wants to sell.
For each distinct item visible in the provided frames:

Required fields (return as JSON array of objects):
- name: product name with model/specs (e.g., "iPhone 15 Pro 256GB Space Black")
- category: one of [electronics, clothing, accessories, home, sports, toys, books, tools, automotive, other]
- condition: one of [new, like_new, good, fair, poor]
- confidence: float 0.0-1.0 indicating identification confidence
- frame_indices: which of the provided frame numbers show this item (list of ints, 0-indexed within this batch)
- bounding_box: [x1, y1, x2, y2] normalized 0-1 for the best frame showing this item
- visible_defects: array of objects with "description" (string) and "severity" ("minor"/"moderate"/"major")
- likely_specs: object mapping spec names to values (brand, model, color, storage, size, etc.)

Return ONLY a valid JSON array. No markdown fences. No extra text.
If no items are visible (hand motion, blur, camera adjustment), return [].

Examples of expected output:

[
  {
    "name": "iPhone 15 Pro 256GB Space Black",
    "category": "electronics",
    "condition": "good",
    "confidence": 0.92,
    "frame_indices": [1, 2, 3],
    "bounding_box": [0.1, 0.15, 0.85, 0.9],
    "visible_defects": [{"description": "Minor scratch on back glass", "severity": "minor"}],
    "likely_specs": {"brand": "Apple", "model": "iPhone 15 Pro", "storage": "256GB", "color": "Space Black"}
  }
]

[
  {
    "name": "Hydro Flask 32oz Wide Mouth Water Bottle",
    "category": "home",
    "condition": "good",
    "confidence": 0.85,
    "frame_indices": [0, 1],
    "bounding_box": [0.2, 0.1, 0.7, 0.95],
    "visible_defects": [{"description": "Dent near base", "severity": "minor"}],
    "likely_specs": {"brand": "Hydro Flask", "size": "32oz", "type": "Wide Mouth"}
  }
]

[
  {
    "name": "iPad Air 5th Gen 64GB Space Gray",
    "category": "electronics",
    "condition": "like_new",
    "confidence": 0.88,
    "frame_indices": [2, 3, 4],
    "bounding_box": [0.05, 0.1, 0.9, 0.85],
    "visible_defects": [],
    "likely_specs": {"brand": "Apple", "model": "iPad Air 5th Gen", "storage": "64GB", "color": "Space Gray"}
  }
]

Important notes:
- Multiple items per batch is normal. Return all visible distinct items.
- The same item across multiple frames should be ONE entry with multiple frame_indices.
- Distinguish between items that look similar but are different (e.g., two iPhones).
- If an item is partially obscured, still identify it with lower confidence.
- Bounding boxes should tightly crop the item, not include background.
"""


# ── Gemini Client Management ─────────────────────────────────────────────────
# Round-robin across configured API keys. Per gemini-pipeline-optimization.md,
# keys should be from SEPARATE GCP projects for real rate limit separation.


class _GeminiPool:
    """Manages Gemini API clients with round-robin key distribution."""

    def __init__(self):
        self._clients = []
        self._counter = 0
        self._initialized = False

    def _ensure_init(self):
        if self._initialized:
            return
        from google import genai

        keys = [k for k in [
            settings.gemini_api_key,
            settings.gemini_api_key_2,
            settings.gemini_api_key_3,
            settings.gemini_api_key_4,
            settings.gemini_api_key_5,
            settings.gemini_api_key_6,
            settings.gemini_api_key_7,
            settings.gemini_api_key_8,
            settings.gemini_api_key_9,
        ] if k]

        if not keys:
            logger.warning("No Gemini API keys configured")
            self._initialized = True
            return

        self._clients = [genai.Client(api_key=k) for k in keys]
        self._initialized = True
        logger.info("Gemini pool initialized with %d API key(s)", len(keys))

    def next_client(self):
        """Get next client via round-robin. Returns (client, key_index)."""
        self._ensure_init()
        if not self._clients:
            raise RuntimeError("No Gemini API keys configured — set GEMINI_API_KEY in .env")
        idx = self._counter % len(self._clients)
        self._counter += 1
        return self._clients[idx], idx

    @property
    def key_count(self) -> int:
        self._ensure_init()
        return len(self._clients)


_gemini_pool = _GeminiPool()


# ── Video Duration Check ──────────────────────────────────────────────────────

MAX_VIDEO_DURATION_SEC = 31
MAX_EXTRACTION_FPS = 61.0


async def _get_video_duration(video_path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise ValueError(
            f"ffprobe failed on {video_path}: {stderr.decode(errors='replace')[:300]}"
        )

    try:
        return float(stdout.decode().strip())
    except (ValueError, TypeError):
        raise ValueError(f"Could not parse video duration from ffprobe output: {stdout.decode()[:100]}")


async def _get_video_fps(video_path: str) -> float:
    """Get the video's native frame rate via ffprobe.

    Returns the average fps as a float. Falls back to 30.0 on parse failure.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.warning("ffprobe fps detection failed: %s", stderr.decode(errors="replace")[:200])
        return 30.0

    raw = stdout.decode().strip()
    try:
        # ffprobe returns fps as a fraction like "30/1" or "30000/1001"
        if "/" in raw:
            num, den = raw.split("/", 1)
            return float(num) / float(den)
        return float(raw)
    except (ValueError, TypeError, ZeroDivisionError):
        logger.warning("Could not parse fps from ffprobe output: %s, defaulting to 30", raw)
        return 30.0


# ── Streaming Frame Extraction ────────────────────────────────────────────────


async def extract_frames_streaming(video_path: str, fps: float | None = None):
    """Extract frames from video via ffmpeg pipe, yielding each as it's ready.

    Yields (frame_index, jpeg_bytes) tuples. Frames are JPEG-encoded.
    Uses ffmpeg's image2pipe with mjpeg codec for streaming output.

    If no fps is provided, uses the video's native frame rate capped at 61 fps.
    Raises ValueError if video exceeds MAX_VIDEO_DURATION_SEC (31s).
    """
    # Check duration before starting extraction
    duration = await _get_video_duration(video_path)
    if duration > MAX_VIDEO_DURATION_SEC:
        raise ValueError(
            f"Video is {duration:.1f}s, maximum allowed is {MAX_VIDEO_DURATION_SEC}s"
        )

    if fps is None:
        native_fps = await _get_video_fps(video_path)
        fps = min(native_fps, MAX_EXTRACTION_FPS)
        logger.info("Using native fps %.2f (capped at %.0f)", native_fps, MAX_EXTRACTION_FPS)
    logger.info("Video duration: %.1fs (limit: %ds)", duration, MAX_VIDEO_DURATION_SEC)

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vf", f"fps={fps}",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-q:v", "2",  # High quality JPEG
        "-",
    ]

    logger.info("Starting ffmpeg streaming extraction: %s (%.1f fps)", video_path, fps)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    frame_idx = 0
    buffer = bytearray()
    SOI = b"\xff\xd8"  # JPEG Start of Image
    EOI = b"\xff\xd9"  # JPEG End of Image

    try:
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            buffer.extend(chunk)

            # Extract complete JPEG frames from the buffer
            while True:
                soi_pos = buffer.find(SOI)
                if soi_pos == -1:
                    break
                eoi_pos = buffer.find(EOI, soi_pos + 2)
                if eoi_pos == -1:
                    break

                # Complete JPEG frame found
                frame_bytes = bytes(buffer[soi_pos:eoi_pos + 2])
                buffer = buffer[eoi_pos + 2:]

                yield frame_idx, frame_bytes
                frame_idx += 1

    finally:
        # Ensure process is cleaned up
        if proc.returncode is None:
            proc.kill()
            await proc.wait()

        stderr_out = await proc.stderr.read()
        if proc.returncode and proc.returncode != 0:
            logger.warning(
                "ffmpeg exited with code %d: %s",
                proc.returncode,
                stderr_out.decode(errors="replace")[-500:],
            )

    logger.info("Extracted %d frames from %s", frame_idx, video_path)


# ── Gemini Batch Analysis ─────────────────────────────────────────────────────


async def _analyze_batch(
    frames: list[tuple[int, bytes]],
    batch_id: int,
) -> list[dict]:
    """Send a batch of frames to Gemini Flash-Lite for item detection.

    Args:
        frames: List of (global_frame_index, jpeg_bytes) tuples.
        batch_id: For logging.

    Returns:
        List of raw item dicts from Gemini, or empty list on failure.
    """
    from google.genai import types

    client, key_idx = _gemini_pool.next_client()

    # Build multimodal content: system prompt + images
    parts = [types.Part.from_text(text=DETECTION_PROMPT)]
    for idx, jpeg_bytes in frames:
        parts.append(types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"))

    logger.info(
        "Batch %d: sending %d frames to %s (key %d/%d)",
        batch_id, len(frames), settings.gemini_detection_model,
        key_idx + 1, _gemini_pool.key_count,
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.gemini_detection_model,
            contents=[types.Content(role="user", parts=parts)],
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        items = json.loads(raw)
        if not isinstance(items, list):
            items = [items]

        logger.info("Batch %d: detected %d item(s)", batch_id, len(items))
        return items

    except Exception as exc:
        logger.warning("Batch %d failed (key %d): %s", batch_id, key_idx + 1, exc)

        # Retry once with a different key (per gemini-pipeline-optimization.md)
        try:
            await asyncio.sleep(2)
            retry_client, retry_key_idx = _gemini_pool.next_client()
            logger.info("Batch %d: retrying with key %d", batch_id, retry_key_idx + 1)

            response = await asyncio.to_thread(
                retry_client.models.generate_content,
                model=settings.gemini_detection_model,
                contents=[types.Content(role="user", parts=parts)],
            )

            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            items = json.loads(raw)
            if not isinstance(items, list):
                items = [items]

            logger.info("Batch %d: retry succeeded, %d item(s)", batch_id, len(items))
            return items

        except Exception as retry_exc:
            logger.warning("Batch %d: retry also failed: %s — skipping batch", batch_id, retry_exc)
            return []


def _raw_to_item_card(raw: dict, job_id: str, frame_paths: list[str]) -> ItemCard:
    """Convert a raw Gemini detection dict into an ItemCard."""
    cat_val = raw.get("category", "other")
    try:
        cat = ItemCategory(cat_val)
    except ValueError:
        cat = ItemCategory.OTHER

    visible_defects = []
    for d in raw.get("visible_defects", []):
        if isinstance(d, dict):
            visible_defects.append(DefectSignal(
                description=d.get("description", ""),
                source="visual",
                severity=d.get("severity", "moderate"),
            ))
        elif isinstance(d, str):
            visible_defects.append(DefectSignal(description=d, source="visual"))

    return ItemCard(
        job_id=job_id,
        name_guess=raw.get("name", raw.get("name_guess", "Unknown Item")),
        category=cat,
        likely_specs=raw.get("likely_specs", {}),
        visible_defects=visible_defects,
        confidence=float(raw.get("confidence", 0.5)),
        hero_frame_paths=frame_paths,
    )


# ── Image Pipeline ────────────────────────────────────────────────────────────


async def _prepare_listing_images(
    item_id: str,
    frames: list[tuple[int, bytes]],
    raw_item: dict,
) -> list[str]:
    """Select best frames for an item, crop to bounding box, resize, save.

    Returns list of saved JPEG file paths.
    """
    output_dir = Path(settings.optimized_dir) / item_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get frame indices for this item
    item_frame_indices = raw_item.get("frame_indices", [])
    bbox = raw_item.get("bounding_box")

    # Select frames that match this item, or use all if no indices specified
    selected = []
    for global_idx, jpeg_bytes in frames:
        if not item_frame_indices or global_idx in item_frame_indices:
            selected.append((global_idx, jpeg_bytes))

    if not selected:
        selected = frames[:3]  # Fallback: first 3 frames

    # Limit to 5 best frames
    selected = selected[:5]

    saved_paths = []
    for i, (idx, jpeg_bytes) in enumerate(selected):
        path = output_dir / f"listing_{i + 1}.jpg"
        processed = await asyncio.to_thread(
            _process_listing_image, jpeg_bytes, bbox
        )
        path.write_bytes(processed)
        saved_paths.append(str(path))

    logger.info("Prepared %d listing images for item %s", len(saved_paths), item_id)
    return saved_paths


def _process_listing_image(
    jpeg_bytes: bytes,
    bbox: list[float] | None,
    target_size: tuple[int, int] = (1080, 1080),
) -> bytes:
    """Crop to bounding box (if available), resize, sharpen, return JPEG bytes."""
    img = Image.open(BytesIO(jpeg_bytes))

    # Crop to bounding box if provided [x1, y1, x2, y2] normalized 0-1
    if bbox and len(bbox) == 4:
        w, h = img.size
        x1 = int(bbox[0] * w)
        y1 = int(bbox[1] * h)
        x2 = int(bbox[2] * w)
        y2 = int(bbox[3] * h)
        # Sanity check
        if x2 > x1 and y2 > y1:
            img = img.crop((x1, y1, x2, y2))

    # Resize to target (maintain aspect ratio, pad to square)
    img.thumbnail(target_size, Image.LANCZOS)

    # Sharpen slightly
    from PIL import ImageFilter
    img = img.filter(ImageFilter.SHARPEN)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# ── Main Streaming Analysis Pipeline ──────────────────────────────────────────


async def streaming_analysis(
    video_path: str,
    job_id: str,
) -> list[ItemCard]:
    """Main intake pipeline: extract frames, batch-analyze, yield items.

    This is the core of Person 3's intake work. It:
    1. Streams frames from ffmpeg
    2. Collects them into batches of BATCH_SIZE
    3. Fires each batch to Gemini in parallel (fan-out)
    4. Deduplicates items across batches
    5. Prepares listing images for each identified item

    Returns all identified ItemCards. Items are available as soon as
    any batch completes (via asyncio.as_completed).
    """
    batch_size = settings.intake_batch_size
    frame_buffer: list[tuple[int, bytes]] = []
    all_frames: list[tuple[int, bytes]] = []
    batch_tasks: list[asyncio.Task] = []
    batch_id = 0

    logger.info("Starting streaming analysis for job %s: %s", job_id, video_path)

    # Phase 1: Extract frames and dispatch batches
    async for frame_idx, frame_bytes in extract_frames_streaming(video_path):
        frame_buffer.append((frame_idx, frame_bytes))
        all_frames.append((frame_idx, frame_bytes))

        if len(frame_buffer) >= batch_size:
            task = asyncio.create_task(
                _analyze_batch(frame_buffer.copy(), batch_id)
            )
            batch_tasks.append(task)
            frame_buffer.clear()
            batch_id += 1

    # Flush remaining frames
    if frame_buffer:
        batch_tasks.append(asyncio.create_task(
            _analyze_batch(frame_buffer.copy(), batch_id)
        ))

    total_frames = len(all_frames)
    logger.info("Extracted %d frames, dispatched %d batches", total_frames, len(batch_tasks))

    # Check minimum frame requirement
    if total_frames < settings.intake_min_frames_required:
        logger.error(
            "Only %d frames extracted (minimum %d required) — failing job",
            total_frames, settings.intake_min_frames_required,
        )
        raise ValueError(
            f"Insufficient frames extracted: {total_frames} "
            f"(minimum {settings.intake_min_frames_required})"
        )

    if not batch_tasks:
        logger.warning("No batches to analyze — no frames extracted")
        return []

    # Phase 2: Collect results as they complete (fan-in)
    seen_items: dict[str, dict] = {}  # name -> raw_item (dedup by name)
    for coro in asyncio.as_completed(batch_tasks):
        try:
            result = await coro
        except Exception as exc:
            logger.warning("Batch task raised: %s", exc)
            continue

        for raw_item in result:
            name = raw_item.get("name", raw_item.get("name_guess", ""))
            if not name:
                continue
            # Simple dedup: keep the highest-confidence detection per item name
            existing = seen_items.get(name)
            if existing is None or raw_item.get("confidence", 0) > existing.get("confidence", 0):
                seen_items[name] = raw_item

    logger.info("Detected %d unique item(s) across all batches", len(seen_items))

    # Phase 3: Build ItemCards and prepare listing images
    items: list[ItemCard] = []
    for name, raw_item in seen_items.items():
        item_id = uuid.uuid4().hex[:10]

        # Prepare listing images (crop, resize, save)
        listing_paths = await _prepare_listing_images(item_id, all_frames, raw_item)

        card = _raw_to_item_card(raw_item, job_id, listing_paths)
        card.item_id = item_id
        items.append(card)

        logger.info(
            "Item: %s (confidence=%.0f%%, defects=%d, images=%d)",
            card.name_guess, card.confidence * 100,
            len(card.all_defects), len(listing_paths),
        )

    return items
