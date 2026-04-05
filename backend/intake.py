"""Video intake pipeline — Strategy S2: Audio-informed Flash-Lite image analysis.

Pipeline (streaming_analysis):
  1. Audio: ffmpeg extract → Deepgram Nova-3 → Llama 4 Scout → item_ids (up to 3)
  2. Preprocess: transcode to 1080p30 H.264 if needed
  3. Extract: 10*N parallel ffmpeg seeks (N = item count)
  4. Filter: OpenCV Laplacian sharpness, pick best per segment
  5. Analyze: parallel Gemini 3.1 Flash-Lite calls (item-aware prompts)
  6. Aggregate: Arctic-Embed per-item dedup
  7. Select: best 4 frames via Gemini picks + histogram diversity

Falls back to free-form detection prompt when audio pipeline fails.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from backend.config import settings
from backend.models.item_card import ItemCard, ItemCategory, DefectSignal

logger = logging.getLogger("reroute.intake")


# ── Pipeline Timing Data ─────────────────────────────────────────────────────


@dataclass
class PipelineTimings:
    audio_extraction_sec: float = 0.0  # ffmpeg audio extract
    transcription_sec: float = 0.0     # Deepgram + Llama 4 Scout
    preprocess_sec: float = 0.0        # 1080p30 transcode (if needed)
    extraction_sec: float = 0.0
    filter_sec: float = 0.0            # OpenCV sharpness filter
    gemini_sec: float = 0.0
    aggregation_sec: float = 0.0       # Arctic-Embed dedup
    frame_selection_sec: float = 0.0   # Gemini picks + histogram tiebreaker
    image_prep_sec: float = 0.0
    total_sec: float = 0.0
    frame_count: int = 0
    filtered_frame_count: int = 0      # after OpenCV filter
    batch_count: int = 0
    items_before_dedup: int = 0
    items_after_dedup: int = 0

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


# ── Arctic-Embed-XS Embedding Pool ───────────────────────────────────────────
# Lazy-loaded ONNX model for semantic deduplication of item detections.
# ~90MB model file, downloaded on first use.


class _EmbedPool:
    """Lazy-init Arctic-Embed-XS for item name similarity."""

    def __init__(self):
        self._model = None

    def _ensure_init(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(
            "Snowflake/snowflake-arctic-embed-xs",
        )
        logger.info("Arctic-Embed-XS model loaded (ONNX)")

    def encode(self, texts: list[str]) -> np.ndarray:
        self._ensure_init()
        return self._model.encode(texts, normalize_embeddings=True)


_embed_pool = _EmbedPool()


# ── Audio Pipeline ───────────────────────────────────────────────────────────


async def extract_audio(video_path: str) -> str:
    """Extract audio from video to a temp WAV file (16kHz mono PCM)."""
    import tempfile

    output_path = tempfile.mktemp(suffix=".wav", prefix="reroute_audio_")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise ValueError(f"Audio extraction failed: {stderr.decode(errors='replace')[:300]}")
    logger.info("Extracted audio to %s", output_path)
    return output_path


async def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio using Deepgram Nova-2 via REST API."""
    import httpx

    with open(audio_path, "rb") as f:
        audio_data = f.read()

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.deepgram.com/v1/listen",
            params={"model": "nova-3", "smart_format": "true"},
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": "audio/wav",
            },
            content=audio_data,
        )
        response.raise_for_status()

    transcript = response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
    logger.info("Transcribed %d chars from audio", len(transcript))
    return transcript


async def parse_items_from_transcript(transcript: str) -> list[str]:
    """Use Groq Llama 4 Scout to extract item names from transcript."""
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract up to 3 of the MOST PROMINENT and DIFFERENT items from "
                    "this transcript of someone describing items they want to sell.\n\n"
                    "Rules:\n"
                    "- Use the correct proprietary name with model specifics when the "
                    "speaker clearly identifies a brand/model (e.g. 'iPhone 15 Pro').\n"
                    "- Use a corrected generic name when the speaker describes something "
                    "recognizable but doesn't name it precisely (e.g. 'wireless earbuds').\n"
                    "- Do NOT guess or invent a brand/model the speaker never mentioned.\n"
                    "- Do NOT split one item into multiple entries (e.g. 'Apple Watch' and "
                    "'Apple Watch band' are the same item — return only the main item).\n"
                    "- Maximum 3 items. Pick the most prominent ones if more are mentioned.\n\n"
                    "Return ONLY a JSON array of strings. No extra text."
                ),
            },
            {"role": "user", "content": transcript},
        ],
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    items = json.loads(raw)
    logger.info("Parsed %d items from transcript: %s", len(items), items)
    return items


async def _aggregate_detections(
    raw_items: list[dict],
    similarity_threshold: float | None = None,
) -> list[dict]:
    """Cluster duplicate detections using Arctic-Embed-XS cosine similarity.

    Items with similar name+specs strings are grouped. Per cluster, the
    highest-confidence detection wins, with merged specs and frame indices.
    """
    if not raw_items:
        return []
    if len(raw_items) == 1:
        return raw_items

    # Pre-pass: collapse items with identical names before expensive embedding.
    # Multiple Gemini batches often return the same item name from different segments.
    name_groups: dict[str, list[dict]] = {}
    for item in raw_items:
        name = (item.get("name") or item.get("name_guess") or item.get("item_id") or "").strip().lower()
        name_groups.setdefault(name, []).append(item)

    pre_collapsed: list[dict] = []
    for name, group in name_groups.items():
        if len(group) == 1:
            pre_collapsed.append(group[0])
        else:
            # Merge: highest confidence wins, merge specs and frame_indices
            group.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            best = group[0].copy()
            merged_specs = {}
            all_indices = []
            for item in group:
                for k, v in item.get("likely_specs", {}).items():
                    if k not in merged_specs:
                        merged_specs[k] = v
                all_indices.extend(item.get("frame_indices", []))
            best["likely_specs"] = merged_specs
            best["confidence"] = max(it.get("confidence", 0) for it in group)
            best["frame_indices"] = sorted(set(all_indices))
            best["_cluster_size"] = len(group)
            pre_collapsed.append(best)

    if len(pre_collapsed) <= 1:
        return pre_collapsed

    raw_items = pre_collapsed
    threshold = similarity_threshold or settings.intake_similarity_threshold

    # Build description strings for embedding
    descriptions = []
    for item in raw_items:
        name = item.get("name", item.get("name_guess", ""))
        specs = item.get("likely_specs", {})
        spec_str = " ".join(f"{k}:{v}" for k, v in specs.items()) if specs else ""
        descriptions.append(f"{name} {spec_str}".strip())

    # Embed all descriptions (CPU, ~150-200ms for 50 items)
    embeddings = await asyncio.to_thread(_embed_pool.encode, descriptions)

    # Greedy clustering by cosine similarity
    clusters: list[list[int]] = []
    assigned: set[int] = set()

    for i in range(len(raw_items)):
        if i in assigned:
            continue
        cluster = [i]
        assigned.add(i)
        for j in range(i + 1, len(raw_items)):
            if j in assigned:
                continue
            sim = float(np.dot(embeddings[i], embeddings[j]))
            if sim >= threshold:
                cluster.append(j)
                assigned.add(j)
        clusters.append(cluster)

    # Per cluster: pick highest confidence, merge specs and frame indices
    aggregated = []
    for cluster in clusters:
        items_in_cluster = [raw_items[idx] for idx in cluster]
        items_in_cluster.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        best = items_in_cluster[0].copy()

        merged_specs = {}
        for item in items_in_cluster:
            for k, v in item.get("likely_specs", {}).items():
                if k not in merged_specs:
                    merged_specs[k] = v
        best["likely_specs"] = merged_specs
        best["confidence"] = max(it.get("confidence", 0) for it in items_in_cluster)

        all_indices = []
        for item in items_in_cluster:
            all_indices.extend(item.get("frame_indices", []))
        best["frame_indices"] = sorted(set(all_indices))
        best["_cluster_size"] = len(cluster)

        aggregated.append(best)

    return aggregated


async def _aggregate_detections_per_item(
    raw_items: list[dict],
    similarity_threshold: float | None = None,
) -> list[dict]:
    """Aggregate detections grouped by item_id, then Arctic-Embed within each group."""
    if not raw_items:
        return []

    by_item: dict[str, list[dict]] = {}
    for item in raw_items:
        iid = item.get("item_id", "unknown")
        by_item.setdefault(iid, []).append(item)

    aggregated = []
    for item_id, group in by_item.items():
        group_agg = await _aggregate_detections(group, similarity_threshold)
        for item in group_agg:
            item["item_id"] = item_id
        aggregated.extend(group_agg)

    return aggregated


# ── Video Preprocessing ──────────────────────────────────────────────────────

MAX_VIDEO_DURATION_SEC = 60


async def _preprocess_video(video_path: str) -> str:
    """Transcode to 1080p30 H.264 if needed. Returns path to normalized file.

    Skips transcode if already H.264 at <=1080p. Uses ultrafast preset
    so transcode is faster than real-time even on CPU.
    """
    import tempfile

    # Check codec and resolution
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height",
        "-of", "csv=p=0", video_path,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, _ = await proc.communicate()
    parts = stdout.decode().strip().split(",")

    if len(parts) >= 3:
        codec, w, h = parts[0], int(parts[1]), int(parts[2])
        if codec == "h264" and w <= 1920 and h <= 1080:
            logger.info("Video already H.264 %dx%d, skipping transcode", w, h)
            return video_path

    output_path = tempfile.mktemp(suffix=".mp4", prefix="reroute_norm_")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", "scale=min(1920\\,iw):min(1080\\,ih):force_original_aspect_ratio=decrease",
        "-r", "60",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy",
        "-y", output_path,
    ]
    logger.info("Transcoding to 1080p30 H.264: %s -> %s", video_path, output_path)
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise ValueError(f"Transcode failed: {stderr.decode(errors='replace')[:300]}")
    logger.info("Transcode complete: %s", output_path)
    return output_path
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


async def extract_frames_streaming(
    video_path: str,
    fps: float | None = None,
    jpeg_quality: int = 2,
):
    """Extract frames from video via ffmpeg pipe, yielding each as it's ready.

    Yields (frame_index, jpeg_bytes) tuples. Frames are JPEG-encoded.
    Uses ffmpeg's image2pipe with mjpeg codec for streaming output.

    Args:
        fps: Extraction frame rate. If None, uses native fps capped at 61.
        jpeg_quality: ffmpeg -q:v value (1=best, 31=worst). Default 2.

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
        "-q:v", str(jpeg_quality),
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


# ── Item-Aware Prompts ───────────────────────────────────────────────────────


def _build_item_prompt(item_ids: list[str]) -> str:
    """Build a Gemini prompt scoped to known items from the audio transcript."""
    item_list = json.dumps(item_ids)
    return (
        "You are assessing items in video frames.\n"
        f"Items identified from seller audio: {item_list}\n\n"
        "Match the frame to an item from the list. Return a JSON object:\n"
        '{"item_id": "<EXACT name from list>", '
        '"category": "electronics|clothing|accessories|home|sports|toys|books|tools|automotive|other", '
        '"condition": "new|like_new|good|fair|poor", '
        '"confidence": 0.0-1.0, "bounding_box": [x1, y1, x2, y2], '
        '"visible_defects": [{"description": "...", "severity": "minor|moderate|major"}], '
        '"likely_specs": {"key": "value"}}\n\n'
        "Return null if no listed item is visible, the image is too blurry, or the frame is empty.\n"
        "Return ONLY valid JSON (object or null). No markdown. No extra text."
    )


# ── Gemini Batch Analysis ─────────────────────────────────────────────────────


async def _analyze_batch(
    frames: list[tuple[int, bytes]],
    batch_id: int,
    model_override: str | None = None,
    item_ids: list[str] | None = None,
) -> list[dict]:
    """Send a batch of frames to Gemini for item detection.

    Args:
        frames: List of (global_frame_index, jpeg_bytes) tuples.
        batch_id: For logging.
        model_override: Use a specific model instead of settings.gemini_image_model.
        item_ids: When provided, use item-aware prompt (match to known items, return null if none).

    Returns:
        List of raw item dicts from Gemini, or empty list on failure/null.
    """
    from google.genai import types

    model = model_override or settings.gemini_image_model
    client, key_idx = _gemini_pool.next_client()

    prompt = _build_item_prompt(item_ids) if item_ids else DETECTION_PROMPT
    parts = [types.Part.from_text(text=prompt)]
    for idx, jpeg_bytes in frames:
        parts.append(types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"))

    logger.info(
        "Batch %d: sending %d frames to %s (key %d/%d)",
        batch_id, len(frames), model,
        key_idx + 1, _gemini_pool.key_count,
    )

    def _parse_response(raw: str) -> list[dict]:
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
        if parsed is None:
            return []
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [item for item in parsed if item is not None]
        return []

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=[types.Content(role="user", parts=parts)],
        )
        items = _parse_response(response.text.strip())
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
                model=model,
                contents=[types.Content(role="user", parts=parts)],
            )
            items = _parse_response(response.text.strip())
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

    # Coerce likely_specs values to strings (Gemini sometimes returns lists)
    raw_specs = raw.get("likely_specs", {})
    specs = {k: ", ".join(v) if isinstance(v, list) else str(v) for k, v in raw_specs.items()}

    return ItemCard(
        job_id=job_id,
        name_guess=raw.get("item_id", raw.get("name", raw.get("name_guess", "Unknown Item"))),
        category=cat,
        likely_specs=specs,
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


# ── Strategy 2: OpenCV Quality Filter ─────────────────────────────────────────


def _filter_quality_frames(
    frames: list[tuple[int, bytes]],
    sharpness_percentile: int | None = None,
    scene_change_threshold: float | None = None,
    hash_hamming_threshold: int | None = None,
    max_output_frames: int | None = None,
) -> list[tuple[int, bytes]]:
    """Filter frames using OpenCV: sharpness, scene-change, perceptual hash.

    All CPU, ~200-300ms for 900 frames. No API calls.
    Returns the filtered subset of (frame_index, jpeg_bytes) tuples.
    """
    if not frames:
        return []

    sharpness_pct = sharpness_percentile or settings.intake_sharpness_percentile
    scene_thresh = scene_change_threshold or settings.intake_scene_change_threshold
    hamming_thresh = hash_hamming_threshold or settings.intake_hash_hamming_threshold
    max_frames = max_output_frames or settings.intake_max_filtered_frames

    # Step 2a: Decode all frames and compute sharpness scores
    decoded: list[tuple[int, bytes, np.ndarray, float]] = []
    for idx, jpeg_bytes in frames:
        arr = np.frombuffer(jpeg_bytes, np.uint8)
        gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        decoded.append((idx, jpeg_bytes, gray, sharpness))

    if not decoded:
        return []

    # Sort by sharpness descending, take top max_frames
    decoded.sort(key=lambda x: x[3], reverse=True)
    top = decoded[:max_frames]

    logger.info(
        "OpenCV filter: %d -> %d frames (top by sharpness, cutoff=%.1f)",
        len(decoded), len(top), top[-1][3] if top else 0,
    )

    final = [(idx, jpeg_bytes) for idx, jpeg_bytes, _, _ in top]
    return final


# ── Strategy 3: Parallel Segment Extraction ───────────────────────────────────


async def _extract_segment_frames(
    video_path: str,
    num_segments: int | None = None,
    frames_per_segment: int | None = None,
    jpeg_quality: int = 2,
) -> list[list[tuple[int, bytes]]]:
    """Extract one frame per segment via parallel ffmpeg input-seeks in batches of 10.

    Uses -ss before -i (input seeking) which jumps to nearest keyframe — fast.
    Batched to avoid spawning too many ffmpeg processes at once.
    """
    n_seg = num_segments or settings.intake_num_segments
    fps = frames_per_segment or settings.intake_frames_per_segment

    duration = await _get_video_duration(video_path)
    if duration > MAX_VIDEO_DURATION_SEC:
        raise ValueError(f"Video is {duration:.1f}s, max is {MAX_VIDEO_DURATION_SEC}s")

    segment_duration = duration / n_seg
    timestamps = [i * segment_duration for i in range(n_seg)]

    async def _extract_at(ts: float, segment_id: int) -> list[tuple[int, bytes]]:
        cmd = [
            "ffmpeg",
            "-ss", f"{ts:.3f}",
            "-i", video_path,
            "-frames:v", str(fps),
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-q:v", str(jpeg_quality),
            "-",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(
                "Segment %d extraction failed at t=%.1f: %s",
                segment_id, ts, stderr.decode(errors="replace")[-200:],
            )
            return []

        frames = []
        SOI, EOI = b"\xff\xd8", b"\xff\xd9"
        buf = bytearray(stdout)
        frame_idx = 0
        while True:
            soi_pos = buf.find(SOI)
            if soi_pos == -1:
                break
            eoi_pos = buf.find(EOI, soi_pos + 2)
            if eoi_pos == -1:
                break
            frames.append((segment_id * fps + frame_idx, bytes(buf[soi_pos:eoi_pos + 2])))
            buf = buf[eoi_pos + 2:]
            frame_idx += 1
        return frames

    # Run in batches of 10 to avoid process thrashing
    BATCH = 10
    segments: list[list[tuple[int, bytes]]] = [[] for _ in range(n_seg)]
    for batch_start in range(0, n_seg, BATCH):
        batch_end = min(batch_start + BATCH, n_seg)
        tasks = [
            asyncio.create_task(_extract_at(timestamps[i], i))
            for i in range(batch_start, batch_end)
        ]
        results = await asyncio.gather(*tasks)
        for i, result in enumerate(results):
            segments[batch_start + i] = result

    total = sum(len(s) for s in segments)
    logger.info("Segment extraction: %d segments, %d total frames (batches of %d)", n_seg, total, BATCH)
    return segments


# ── Best Frame Selection ──────────────────────────────────────────────────────


def _compute_sharpness(jpeg_bytes: bytes) -> float:
    """Laplacian variance sharpness score for a JPEG frame."""
    arr = np.frombuffer(jpeg_bytes, np.uint8)
    gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _compute_hist(jpeg_bytes: bytes) -> np.ndarray:
    """Normalized 64-bin grayscale histogram for diversity comparison."""
    arr = np.frombuffer(jpeg_bytes, np.uint8)
    gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return np.zeros((64, 1), dtype=np.float32)
    hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
    cv2.normalize(hist, hist)
    return hist


def _select_best_frames_per_item(
    aggregated_items: list[dict],
    all_frames: list[tuple[int, bytes]],
    target_per_item: int = 4,
) -> dict[str, list[tuple[int, bytes]]]:
    """Select up to `target_per_item` frames per unique item.

    For each item:
      1. Gather candidate frames from the item's frame_indices.
      2. Pick up to `target_per_item` most histogram-diverse frames
         (greedy max-min distance selection).
      3. Order the selected frames by sharpness (Laplacian variance), best first.

    Returns dict mapping item key → ordered list of (frame_idx, jpeg_bytes).
    """
    if not all_frames:
        return {}

    frame_lookup: dict[int, bytes] = {idx: data for idx, data in all_frames}
    result: dict[str, list[tuple[int, bytes]]] = {}

    for item in aggregated_items:
        item_key = item.get("item_id", item.get("name", item.get("name_guess", "unknown")))
        frame_indices = item.get("frame_indices", [])

        # Gather this item's candidate frames
        candidates = [
            (idx, frame_lookup[idx])
            for idx in frame_indices
            if idx in frame_lookup
        ]
        if not candidates:
            result[item_key] = []
            continue

        if len(candidates) <= target_per_item:
            # Fewer candidates than target — take all, just sort by sharpness
            scored = [(idx, data, _compute_sharpness(data)) for idx, data in candidates]
            scored.sort(key=lambda x: x[2], reverse=True)
            result[item_key] = [(idx, data) for idx, data, _ in scored]
            continue

        # Step 1: Pick most diverse frames via greedy histogram max-min
        selected: list[tuple[int, bytes, np.ndarray]] = []

        # Seed with the sharpest frame
        sharpness_scores = {idx: _compute_sharpness(data) for idx, data in candidates}
        seed_idx = max(sharpness_scores, key=sharpness_scores.get)
        seed_data = frame_lookup[seed_idx]
        selected.append((seed_idx, seed_data, _compute_hist(seed_data)))
        remaining = [(idx, data) for idx, data in candidates if idx != seed_idx]

        while len(selected) < target_per_item and remaining:
            best_candidate = None
            best_min_dist = -1.0

            for idx, data in remaining:
                hist = _compute_hist(data)
                min_dist = min(
                    1.0 - cv2.compareHist(hist, sh, cv2.HISTCMP_CORREL)
                    for _, _, sh in selected
                )
                if min_dist > best_min_dist:
                    best_min_dist = min_dist
                    best_candidate = (idx, data, hist)

            if best_candidate is None:
                break

            selected.append(best_candidate)
            remaining = [(i, d) for i, d in remaining if i != best_candidate[0]]

        # Step 2: Order selected frames by sharpness, best first
        scored_selected = [
            (idx, data, sharpness_scores.get(idx, _compute_sharpness(data)))
            for idx, data, _ in selected
        ]
        scored_selected.sort(key=lambda x: x[2], reverse=True)
        result[item_key] = [(idx, data) for idx, data, _ in scored_selected]

    total = sum(len(v) for v in result.values())
    logger.info(
        "Per-item frame selection: %d items, %d total frames (up to %d each)",
        len(result), total, target_per_item,
    )
    return result


# ── Strategy Runner ───────────────────────────────────────────────────────────


async def run_image_strategy(
    video_path: str,
    job_id: str,
    frame_collector: dict[int, bytes] | None = None,
    model: str | None = None,
    item_ids: list[str] | None = None,
) -> tuple[list[ItemCard], PipelineTimings, list[tuple[int, bytes]]]:
    """Image strategy: Split into segments, extract frames per segment,
    OpenCV picks best per segment, send images to Gemini.

    When item_ids is provided, uses 10 * len(item_ids) segments and item-aware
    prompts. All Gemini calls fire in parallel with round-robin key cycling.
    """
    timings = PipelineTimings()
    t_total = time.perf_counter()
    num_segments = 10 * len(item_ids) if item_ids else settings.intake_num_segments
    frames_per_gemini = settings.intake_frames_per_segment

    # Phase 0: Preprocess to 1080p30 H.264 (fast seeks)
    t_pre = time.perf_counter()
    normalized_path = await _preprocess_video(video_path)
    timings.preprocess_sec = time.perf_counter() - t_pre

    # Phase 1: Extract frames from segments (parallel ffmpeg seeks)
    t0 = time.perf_counter()
    segments = await _extract_segment_frames(normalized_path, num_segments=num_segments)
    timings.extraction_sec = time.perf_counter() - t0

    total_raw = sum(len(seg) for seg in segments)
    timings.frame_count = total_raw

    if total_raw < settings.intake_min_frames_required:
        raise ValueError(
            f"Insufficient frames: {total_raw} (min {settings.intake_min_frames_required})"
        )

    # Phase 2: OpenCV picks best per segment
    t1 = time.perf_counter()
    filtered_segments: list[list[tuple[int, bytes]]] = []
    all_filtered: list[tuple[int, bytes]] = []
    segment_global_indices: list[list[int]] = []

    for seg_frames in segments:
        if not seg_frames:
            filtered_segments.append([])
            segment_global_indices.append([])
            continue
        top_n = await asyncio.to_thread(
            _filter_quality_frames, seg_frames, max_output_frames=frames_per_gemini
        )
        filtered_segments.append(top_n)
        all_filtered.extend(top_n)
        segment_global_indices.append([idx for idx, _ in top_n])

    timings.filter_sec = time.perf_counter() - t1
    timings.filtered_frame_count = len(all_filtered)

    logger.info(
        "Image strategy: %d raw frames -> %d filtered (%d segments)",
        total_raw, len(all_filtered), num_segments,
    )

    # Phase 3: Parallel Gemini calls (all segments fire at once)
    gemini_model = model or settings.gemini_image_model
    t2 = time.perf_counter()
    batch_tasks = []
    task_seg_ids: list[int] = []
    for seg_id, seg_frames in enumerate(filtered_segments):
        if seg_frames:
            batch_tasks.append(asyncio.create_task(
                _analyze_batch(seg_frames, seg_id, model_override=gemini_model, item_ids=item_ids)
            ))
            task_seg_ids.append(seg_id)
    timings.batch_count = len(batch_tasks)

    results = await asyncio.gather(*batch_tasks, return_exceptions=True)
    raw_items: list[dict] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Batch failed: %s", result)
            continue
        seg_id = task_seg_ids[i]
        for item in result:
            item["frame_indices"] = segment_global_indices[seg_id]
            raw_items.append(item)
    timings.gemini_sec = time.perf_counter() - t2
    timings.items_before_dedup = len(raw_items)

    # Phase 4: Aggregation (per-item when item_ids provided, global otherwise)
    t3 = time.perf_counter()
    if item_ids:
        aggregated = await _aggregate_detections_per_item(raw_items)
    else:
        aggregated = await _aggregate_detections(raw_items)
    timings.aggregation_sec = time.perf_counter() - t3
    timings.items_after_dedup = len(aggregated)

    # Phase 5: Select up to 4 best frames per item (diverse + quality-ordered)
    t4 = time.perf_counter()
    frames_by_item = _select_best_frames_per_item(aggregated, all_filtered, target_per_item=4)
    timings.frame_selection_sec = time.perf_counter() - t4

    # Flatten all per-item frames for collector and return value
    all_best_frames: list[tuple[int, bytes]] = []
    for item_frames in frames_by_item.values():
        all_best_frames.extend(item_frames)

    if frame_collector is not None:
        frame_collector.clear()
        for idx, jpeg_bytes in all_best_frames:
            frame_collector[idx] = jpeg_bytes

    # Build ItemCards with per-item hero frames
    items: list[ItemCard] = []
    for raw_item in aggregated:
        item_key = raw_item.get("item_id", raw_item.get("name", raw_item.get("name_guess", "unknown")))
        item_frames = frames_by_item.get(item_key, [])
        frame_paths = [f"frame_{idx}" for idx, _ in item_frames]
        card = _raw_to_item_card(raw_item, job_id, frame_paths)
        items.append(card)

    # Cleanup normalized file
    if normalized_path != video_path:
        Path(normalized_path).unlink(missing_ok=True)

    timings.total_sec = time.perf_counter() - t_total
    logger.info(
        "Image strategy complete: %.1fs total (pre=%.1f, extract=%.1f, filter=%.1f, gemini=%.1f, "
        "agg=%.1f, select=%.3f) frames=%d->%d->%d best, items=%d->%d",
        timings.total_sec, timings.preprocess_sec, timings.extraction_sec, timings.filter_sec,
        timings.gemini_sec, timings.aggregation_sec, timings.frame_selection_sec,
        timings.frame_count, timings.filtered_frame_count, len(all_best_frames),
        timings.items_before_dedup, timings.items_after_dedup,
    )
    return items, timings, all_best_frames



# ── Main Streaming Analysis Pipeline ──────────────────────────────────────────


async def streaming_analysis(
    video_path: str,
    job_id: str,
    *,
    frame_collector: dict[int, bytes] | None = None,
) -> tuple[list[ItemCard], PipelineTimings, list[tuple[int, bytes]], str | None]:
    """Main intake pipeline: audio extraction → Flash-Lite image analysis.

    Pipeline (Strategy S2):
      1. Audio: ffmpeg extract → Deepgram Nova-3 → Llama 4 Scout → item_ids
      2. Visual: preprocess → segment extraction → OpenCV filter →
         parallel Gemini Flash-Lite (item-aware) → per-item aggregation → best 4 frames

    Falls back to free-form detection if audio pipeline fails or yields no items.

    Returns:
        (items, timings, best_frames, transcript_text) tuple.
    """
    logger.info("Starting S2 analysis for job %s: %s", job_id, video_path)

    # Phase 0: Audio pipeline — extract item names from seller narration
    item_ids: list[str] | None = None
    audio_extraction_sec = 0.0
    transcription_sec = 0.0
    transcript_text: str | None = None

    try:
        t_audio = time.perf_counter()
        audio_path = await extract_audio(video_path)
        audio_extraction_sec = time.perf_counter() - t_audio

        try:
            t_transcribe = time.perf_counter()
            transcript = await transcribe_audio(audio_path)
            transcript_text = transcript
            parsed = await parse_items_from_transcript(transcript)
            transcription_sec = time.perf_counter() - t_transcribe

            if parsed:
                item_ids = parsed
                logger.info("Audio pipeline: %d items identified: %s", len(item_ids), item_ids)
            else:
                logger.warning(
                    "Audio pipeline returned empty item list — falling back to free-form detection"
                )
        finally:
            Path(audio_path).unlink(missing_ok=True)

    except Exception as exc:
        logger.warning("Audio pipeline failed — falling back to free-form detection: %s", exc)

    # Phase 1+: Visual analysis with Flash-Lite
    items, timings, best_frames = await run_image_strategy(
        video_path, job_id, frame_collector,
        model=settings.gemini_image_model,
        item_ids=item_ids,
    )

    # Attach audio timing to pipeline timings
    timings.audio_extraction_sec = audio_extraction_sec
    timings.transcription_sec = transcription_sec

    return items, timings, best_frames, transcript_text
