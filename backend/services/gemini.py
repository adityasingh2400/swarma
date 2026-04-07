from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from pathlib import Path

from google import genai
from google.genai import types

from backend.config import settings
from backend.models.item_card import ItemCard, DefectSignal, ItemCategory
from backend.models.route_bid import ComparableListing

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.1-pro-preview"

MIME_MAP = {
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
    ".3gp": "video/3gpp",
}

import hashlib

_upload_cache: dict[tuple[str, int], object] = {}
_upload_locks: dict[tuple[str, int], asyncio.Lock] = {}
_global_lock = asyncio.Lock()
_content_hash_cache: dict[str, str] = {}

# ── Demo pre-computation caches ──────────────────────────────────────────────
# Keyed by video content hash — identical video content hits cache regardless of filename
_transcript_cache: dict[str, str] = {}
_analysis_cache: dict[str, list[dict]] = {}
# Keyed by "item_name|condition|platform1,platform2,..."
_search_cache: dict[str, list] = {}
# Keyed by item name
_listing_cache: dict[str, dict] = {}

# ── Snapshot persistence ─────────────────────────────────────────────────────
_DEMO_CACHE_DIR = Path(__file__).resolve().parent.parent / ".swarmsellcache"
_SNAPSHOT_PATH = _DEMO_CACHE_DIR / "snapshot.json"
_SNAPSHOT_FRAMES_DIR = _DEMO_CACHE_DIR / "frames"


def load_demo_snapshot() -> bool:
    """Load all pre-computed demo data from disk into memory caches.
    Returns True if snapshot exists and was loaded successfully."""
    if not _SNAPSHOT_PATH.exists():
        return False
    try:
        snapshot = json.loads(_SNAPSHOT_PATH.read_text())
    except Exception:
        return False

    content_hash = snapshot.get("content_hash", "")
    if not content_hash:
        return False

    # Populate transcript + analysis caches
    _transcript_cache[content_hash] = snapshot["transcript"]
    _analysis_cache[content_hash] = snapshot["analysis_items"]

    # Populate search cache (reconstruct ComparableListing objects)
    for key, comps_data in snapshot.get("searches", {}).items():
        _search_cache[key] = [
            ComparableListing(
                platform=c.get("platform", ""), title=c.get("title", ""),
                price=c.get("price", 0.0), shipping=c.get("shipping", ""),
                condition=c.get("condition", ""), url=c.get("url", ""),
                image_url=c.get("image_url", ""), match_score=c.get("match_score", 70),
            )
            for c in comps_data
        ]

    # Populate listing cache
    _listing_cache.update(snapshot.get("listings", {}))

    # Copy snapshot frames to data/frames/ and populate frame cache
    import shutil
    frames_dir = Path(settings.frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    for fname in snapshot.get("frame_filenames", []):
        src = _SNAPSHOT_FRAMES_DIR / fname
        dest = frames_dir / fname
        if src.exists() and not dest.exists():
            shutil.copy2(str(src), str(dest))
        if dest.exists():
            frame_paths.append(str(dest))

    if frame_paths:
        from backend.services.media import preload_frame_cache
        preload_frame_cache(content_hash, frame_paths)

    n_searches = len(snapshot.get("searches", {}))
    n_listings = len(snapshot.get("listings", {}))
    print(f"[SNAPSHOT] Loaded: {len(snapshot.get('analysis_items', []))} items, "
          f"{n_searches} search groups, {n_listings} listings, "
          f"{len(frame_paths)} frames (hash: {content_hash[:8]}…)")
    return True


def _save_demo_snapshot(
    content_hash: str,
    transcript: str,
    analysis_items_raw: list[dict],
    frame_paths: list[str],
) -> None:
    """Persist all pre-computed demo data to disk for instant loading."""
    import shutil

    _DEMO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT_FRAMES_DIR.mkdir(parents=True, exist_ok=True)

    # Copy frame files with stable names
    frame_filenames = []
    for i, fp in enumerate(frame_paths):
        src = Path(fp)
        if src.exists():
            dest_name = f"demo_{i + 1:04d}.jpg"
            shutil.copy2(str(src), str(_SNAPSHOT_FRAMES_DIR / dest_name))
            frame_filenames.append(dest_name)

    # Serialize search cache
    searches = {}
    for key, results in _search_cache.items():
        searches[key] = [
            {"platform": c.platform, "title": c.title, "price": c.price,
             "shipping": c.shipping, "condition": c.condition, "url": c.url,
             "image_url": c.image_url, "match_score": c.match_score}
            for c in results
        ]

    snapshot = {
        "version": 1,
        "content_hash": content_hash,
        "transcript": transcript,
        "analysis_items": analysis_items_raw,
        "searches": searches,
        "listings": dict(_listing_cache),
        "frame_filenames": frame_filenames,
    }

    _SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2))
    print(f"[SNAPSHOT] Saved: {len(analysis_items_raw)} items, "
          f"{len(searches)} search groups, {len(_listing_cache)} listings, "
          f"{len(frame_filenames)} frames → {_SNAPSHOT_PATH}")


def _file_content_hash(path: str) -> str:
    """Fast MD5 of first+last 2MB — enough to fingerprint identical videos."""
    cached = _content_hash_cache.get(path)
    if cached:
        return cached
    h = hashlib.md5()
    size = Path(path).stat().st_size
    chunk = 2 * 1024 * 1024
    with open(path, "rb") as f:
        h.update(f.read(chunk))
        if size > chunk * 2:
            f.seek(-chunk, 2)
            h.update(f.read(chunk))
    digest = h.hexdigest()
    _content_hash_cache[path] = digest
    return digest


def _get_mime_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in MIME_MAP:
        return MIME_MAP[ext]
    guess, _ = mimetypes.guess_type(path)
    return guess or "video/mp4"


def _frame_path_to_url(path: str) -> str:
    """Convert a filesystem frame path to a URL served by the static mount."""
    return f"/frames/{Path(path).name}"


def _parse_defects(raw_list: list, source: str) -> list[DefectSignal]:
    result = []
    for d in raw_list:
        if isinstance(d, dict):
            result.append(DefectSignal(
                description=d.get("description", ""),
                source=source,
                severity=d.get("severity", "moderate"),
            ))
        elif isinstance(d, str):
            result.append(DefectSignal(description=d, source=source, severity="moderate"))
    return result


def _parse_items_data(
    items_data: list[dict],
    frame_paths: list[str],
) -> list[ItemCard]:
    """Parse raw Gemini JSON items into ItemCards, optionally assigning hero frames."""
    cards: list[ItemCard] = []
    total_frames = len(frame_paths)

    for item_idx, item in enumerate(items_data):
        hero_frame_urls: list[str] = []
        if frame_paths:
            hero_frames_fs = _resolve_hero_frames(item, item_idx, frame_paths, len(items_data))
            hero_frame_urls = [_frame_path_to_url(p) for p in hero_frames_fs]

        cat_val = item.get("category", "other")
        try:
            cat = ItemCategory(cat_val)
        except ValueError:
            cat = ItemCategory.OTHER

        card = ItemCard(
            name_guess=item.get("name_guess", "Unknown Item"),
            category=cat,
            likely_specs=item.get("likely_specs", {}),
            visible_defects=_parse_defects(item.get("visible_defects", []), "visual"),
            spoken_defects=_parse_defects(item.get("spoken_defects", []), "spoken"),
            accessories_included=item.get("accessories_included", []),
            accessories_missing=item.get("accessories_missing", []),
            confidence=float(item.get("confidence", 0.5)),
            hero_frame_paths=hero_frame_urls,
            all_frame_paths=frame_paths,
            segment_start_sec=float(item.get("segment_start_sec", 0.0)),
            segment_end_sec=float(item.get("segment_end_sec", 0.0)),
            hero_frame_indices_raw=item.get("hero_frame_indices", []),
        )
        cards.append(card)
    return cards


def _resolve_hero_frames(
    item: dict,
    item_idx: int,
    frame_paths: list[str],
    total_items: int,
) -> list[str]:
    """Map Gemini's hero_frame_indices to actual frame filesystem paths,
    with segment-based and even-distribution fallbacks."""
    total_frames = len(frame_paths)
    hero_indices = item.get("hero_frame_indices", [])
    hero_frames_fs = [frame_paths[i] for i in hero_indices if 0 <= i < total_frames]

    if not hero_frames_fs and frame_paths:
        seg_start = float(item.get("segment_start_sec", 0))
        seg_end = float(item.get("segment_end_sec", 0))
        if seg_end > seg_start and total_frames > 1:
            video_duration = max(seg_end * 1.2, 30.0)
            start_idx = max(0, int(seg_start / video_duration * total_frames))
            end_idx = min(total_frames, int(seg_end / video_duration * total_frames) + 1)
            segment_frames = frame_paths[start_idx:end_idx]
            if segment_frames:
                step = max(1, len(segment_frames) // 3)
                hero_frames_fs = segment_frames[::step][:3]
        if not hero_frames_fs:
            chunk = max(1, total_frames // max(total_items, 1))
            start = item_idx * chunk
            hero_frames_fs = frame_paths[start:start + min(3, chunk)]

    return hero_frames_fs


def assign_hero_frames(cards: list[ItemCard], frame_paths: list[str]) -> list[ItemCard]:
    """Assign hero frame paths to ItemCards that were created without frame data.

    Used in the fused pipeline where analysis completes before frame extraction.
    Reads each card's hero_frame_indices_raw (stored from the Gemini response) to
    map indices to actual filesystem paths.
    """
    total_frames = len(frame_paths)
    for item_idx, card in enumerate(cards):
        raw_item = {
            "hero_frame_indices": card.hero_frame_indices_raw,
            "segment_start_sec": card.segment_start_sec,
            "segment_end_sec": card.segment_end_sec,
        }
        hero_fs = _resolve_hero_frames(raw_item, item_idx, frame_paths, len(cards))
        card.hero_frame_paths = [_frame_path_to_url(p) for p in hero_fs]
        card.all_frame_paths = frame_paths
    return cards


def _extract_segment_transcript(
    full_transcript: str, start_sec: float, end_sec: float
) -> str:
    """Best-effort extraction of the transcript portion for a time segment.

    Since we don't have word-level timestamps, we split the transcript
    proportionally by the segment's position in the video. This is a rough
    heuristic but provides useful context per item.
    """
    if not full_transcript or end_sec <= start_sec:
        return full_transcript

    words = full_transcript.split()
    if not words:
        return ""

    total_duration = max(end_sec * 1.2, 30.0)
    start_frac = max(0.0, start_sec / total_duration)
    end_frac = min(1.0, end_sec / total_duration)

    start_word = int(start_frac * len(words))
    end_word = max(start_word + 1, int(end_frac * len(words)))
    return " ".join(words[start_word:end_word])


async def _upload_video_and_wait(
    client: genai.Client, video_path: str, key_index: int = 0
):
    """Upload video to Gemini and wait until active.

    Caches by (content_hash, key_index) so duplicate files (even with
    different filenames) reuse the same Gemini file reference.  This means
    pre-uploaded demo videos are found instantly on subsequent pipeline runs.
    """
    content_hash = await asyncio.to_thread(_file_content_hash, video_path)
    cache_key = (content_hash, key_index)

    if cache_key in _upload_cache:
        cached = _upload_cache[cache_key]
        print(f"[GEMINI] [Key {key_index + 1}] Reusing cached upload: {cached.name} "
              f"(content hash match: {content_hash[:8]}…)", flush=True)
        return cached

    async with _global_lock:
        if cache_key not in _upload_locks:
            _upload_locks[cache_key] = asyncio.Lock()
        lock = _upload_locks[cache_key]

    async with lock:
        if cache_key in _upload_cache:
            return _upload_cache[cache_key]

        mime = _get_mime_type(video_path)
        print(f"[GEMINI] [Key {key_index + 1}] Uploading video: {video_path} (mime: {mime})")

        with open(video_path, "rb") as f:
            video_file = await asyncio.to_thread(
                client.files.upload, file=f, config={"mime_type": mime}
            )
        print(f"[GEMINI] [Key {key_index + 1}] Upload complete: {video_file.name} (state: {video_file.state})")

        wait_count = 0
        while video_file.state == "PROCESSING":
            wait_count += 1
            print(f"[GEMINI] [Key {key_index + 1}] File still processing... waiting ({wait_count * 3}s)")
            await asyncio.sleep(3)
            video_file = await asyncio.to_thread(client.files.get, name=video_file.name)

        if video_file.state != "ACTIVE":
            raise RuntimeError(f"File {video_file.name} failed processing: state={video_file.state}")

        print(f"[GEMINI] [Key {key_index + 1}] File ready: {video_file.name} (state: ACTIVE)", flush=True)
        _upload_cache[cache_key] = video_file
        return video_file


class GeminiService:
    """Gemini AI service with multi-key round-robin for concurrent requests.

    When multiple API keys are configured (GEMINI_API_KEY through GEMINI_API_KEY_10),
    each concurrent call gets a different key to avoid rate limits. Keys are
    distributed round-robin via an atomic counter.
    """

    _clients: list[genai.Client] = []
    _counter: int = 0
    _initialized: bool = False
    _key_count: int = 0

    def __init__(self) -> None:
        if not GeminiService._initialized:
            GeminiService._init_clients()

    @classmethod
    def _init_clients(cls) -> None:
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
            settings.gemini_api_key_10,
        ] if k]
        if not keys:
            cls._initialized = True
            cls._key_count = 0
            return
        cls._clients = [genai.Client(api_key=k) for k in keys]
        cls._key_count = len(keys)
        cls._initialized = True
        print(f"[GEMINI] ═══ Initialized with {len(keys)} API key(s) for round-robin concurrency ═══")
        for i in range(len(keys)):
            masked = keys[i][:10] + "..." + keys[i][-4:]
            print(f"[GEMINI]   Key {i+1}/{len(keys)}: {masked}")

    @classmethod
    async def preupload_demo_video(cls) -> None:
        """Pre-upload the demo video at server startup so pipeline runs skip
        the ~90s upload entirely. Finds the most recent .MOV/.mp4 in the
        uploads dir, or falls back to test.MOV in the project root."""
        if not cls._initialized or not cls._clients:
            return

        candidates = sorted(
            Path(settings.upload_dir).glob("*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        video = next((c for c in candidates if c.suffix.lower() in MIME_MAP), None)

        if not video:
            fallback = Path("test.MOV")
            if fallback.exists():
                video = fallback
            else:
                print("[GEMINI] ⚠ No demo video found — skipping preupload")
                return

        import time as _t
        t0 = _t.time()
        client, kidx = cls._clients[0], 0
        print(f"[GEMINI] ═══ Pre-uploading demo video: {video.name} ({video.stat().st_size / 1024 / 1024:.0f}MB) ═══")

        try:
            file_ref = await _upload_video_and_wait(client, str(video), key_index=kidx)
            elapsed = _t.time() - t0
            print(f"[GEMINI] ═══ Pre-upload complete in {elapsed:.1f}s — "
                  f"{file_ref.name} (hash: {_file_content_hash(str(video))[:8]}…) ═══",
                  flush=True)
        except Exception as exc:
            print(f"[GEMINI] ⚠ Pre-upload failed (non-fatal): {exc}", flush=True)

    @classmethod
    async def precompute_demo_pipeline(cls) -> None:
        """Full demo warmup: pre-upload, pre-extract frames, pre-analyze,
        and pre-search marketplaces so the pipeline runs instantly."""
        if not cls._initialized or not cls._clients:
            return

        from backend.services.media import MediaService

        # ── Find the demo video ──
        candidates = sorted(
            Path(settings.upload_dir).glob("*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        video = next((c for c in candidates if c.suffix.lower() in MIME_MAP), None)
        if not video:
            fallback = Path("test.MOV")
            if fallback.exists():
                video = fallback
            else:
                print("[WARMUP] ⚠ No demo video found — skipping pre-computation")
                return

        import time as _t
        video_path = str(video)
        t_total = _t.time()
        print(f"[WARMUP] ═══ Full pipeline pre-computation starting: {video.name} ═══")

        svc = cls()
        media = MediaService()
        client, kidx = cls._clients[0], 0

        # ── Phase 1: Upload + Frames (parallel) ──
        t0 = _t.time()
        upload_task = asyncio.create_task(_upload_video_and_wait(client, video_path, key_index=kidx))
        frames_task = asyncio.create_task(media.extract_frames(video_path))

        results = await asyncio.gather(upload_task, frames_task, return_exceptions=True)
        video_file = results[0] if not isinstance(results[0], BaseException) else None
        frame_paths = results[1] if not isinstance(results[1], BaseException) else []
        print(f"[WARMUP] Phase 1 done in {_t.time()-t0:.1f}s: upload + {len(frame_paths)} frames")

        if not video_file:
            print(f"[WARMUP] ⚠ Upload failed — cannot pre-compute analysis")
            return

        # ── Phase 2: Transcript + Analysis (parallel on same key) ──
        t1 = _t.time()
        transcript_task = asyncio.create_task(
            svc._fused_transcribe_with_file(client, video_file, kidx)
        )
        analysis_task = asyncio.create_task(
            svc._fused_analyze_with_file(client, video_file, kidx, video_path)
        )

        results2 = await asyncio.gather(transcript_task, analysis_task, return_exceptions=True)

        transcript = ""
        items: list[ItemCard] = []

        if not isinstance(results2[0], BaseException):
            transcript = results2[0]
            content_hash = _file_content_hash(video_path)
            _transcript_cache[content_hash] = transcript
            print(f"[WARMUP]   Transcript cached: {len(transcript)} chars")

        if not isinstance(results2[1], BaseException):
            items, items_data_raw = results2[1]
            content_hash = _file_content_hash(video_path)
            _analysis_cache[content_hash] = items_data_raw
            items = assign_hero_frames(items, frame_paths)
            for card in items:
                card.raw_transcript_segment = _extract_segment_transcript(
                    transcript, card.segment_start_sec, card.segment_end_sec
                )
            print(f"[WARMUP]   Analysis cached: {len(items)} items")

        print(f"[WARMUP] Phase 2 done in {_t.time()-t1:.1f}s: transcript + analysis")

        if not items:
            print(f"[WARMUP] ⚠ No items detected — cannot pre-compute searches")
            return

        # ── Phase 3: Marketplace searches (parallel, all 9 keys) ──
        t2 = _t.time()
        platform_groups = [
            ["Swappa", "OfferUp"],
            ["Facebook Marketplace", "Poshmark"],
            ["Amazon", "Craigslist"],
        ]
        search_tasks = []
        for item in items:
            for platforms in platform_groups:
                search_tasks.append(
                    svc.search_platform(item.name_guess, platforms, item.condition_label)
                )

        await asyncio.gather(*search_tasks, return_exceptions=True)
        print(f"[WARMUP] Phase 3 done in {_t.time()-t2:.1f}s: "
              f"{len(search_tasks)} search groups across {len(items)} items")

        # ── Phase 4: Listing generation (parallel, 3 keys) ──
        t3 = _t.time()
        listing_tasks = []
        for item in items:
            # Collect comp prices from cached search results
            comp_prices: list[float] = []
            for platforms in platform_groups:
                ck = f"{item.name_guess}|{item.condition_label}|{','.join(sorted(platforms))}"
                for comp in _search_cache.get(ck, []):
                    if comp.price > 0:
                        comp_prices.append(comp.price)
            listing_tasks.append(svc.generate_listing(item, comp_prices=comp_prices or None))

        await asyncio.gather(*listing_tasks, return_exceptions=True)
        print(f"[WARMUP] Phase 4 done in {_t.time()-t3:.1f}s: {len(listing_tasks)} listings")

        # ── Save snapshot to disk ──
        content_hash = _file_content_hash(video_path)
        items_raw = _analysis_cache.get(content_hash, [])
        _save_demo_snapshot(content_hash, transcript, items_raw, frame_paths)

        total = _t.time() - t_total
        print(f"[WARMUP] ═══ Full pre-computation complete in {total:.1f}s ═══", flush=True)

    def _get_primary_client(self) -> tuple[genai.Client, int]:
        """Primary client (Key 1) — used for video uploads and analysis that
        reference uploaded files. Returns (client, key_index_0based)."""
        if not self._clients:
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY not configured")
            self._clients = [genai.Client(api_key=settings.gemini_api_key)]
            GeminiService._key_count = 1
        return self._clients[0], 0

    def _get_secondary_client(self) -> tuple[genai.Client, int]:
        """Secondary client (Key 2 if available, else Key 1) — used for
        transcription so it can upload and reference the video file concurrently
        with the primary client's analysis. Returns (client, key_index_0based)."""
        if not self._clients:
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY not configured")
            self._clients = [genai.Client(api_key=settings.gemini_api_key)]
            GeminiService._key_count = 1
        idx = min(1, len(self._clients) - 1)
        return self._clients[idx], idx

    def _get_client(self) -> genai.Client:
        """Round-robin client — used for search_live_comps and other calls
        that don't reference uploaded files."""
        if not self._clients:
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY not configured")
            self._clients = [genai.Client(api_key=settings.gemini_api_key)]
            GeminiService._key_count = 1
        idx = GeminiService._counter % len(self._clients)
        GeminiService._counter += 1
        return self._clients[idx]

    def _get_client_with_id(self) -> tuple[genai.Client, int, int]:
        """Round-robin client with key metadata for logging.
        Returns (client, key_index_1based, total_keys)."""
        if not self._clients:
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY not configured")
            self._clients = [genai.Client(api_key=settings.gemini_api_key)]
            GeminiService._key_count = 1
        idx = GeminiService._counter % len(self._clients)
        GeminiService._counter += 1
        return self._clients[idx], idx + 1, len(self._clients)

    @classmethod
    def get_key_count(cls) -> int:
        return cls._key_count

    async def analyze_video(
        self,
        video_path: str,
        transcript: str = "",
        frame_paths: list[str] | None = None,
    ) -> list[ItemCard]:
        """Analyze video to identify items, condition, and defects.

        The transcript parameter is optional -- when empty, the prompt instructs
        Gemini to listen to the audio track directly. frame_paths is also optional;
        when provided, hero frames are assigned inline. When omitted (fused mode),
        the caller is responsible for assigning hero frames after the fact via
        assign_hero_frames().
        """
        if settings.demo_mode and not settings.gemini_api_key:
            return self._mock_analyze(frame_paths)

        try:
            client, kidx = self._get_primary_client()

            has_frames = bool(frame_paths)
            n_frames = len(frame_paths) if has_frames else 0

            if transcript:
                transcript_block = (
                    "Transcript of user speech:\n" + transcript
                )
            else:
                transcript_block = (
                    "IMPORTANT: Listen carefully to ALL speech in the video's audio track. "
                    "The user describes each item verbally, mentioning defects, condition, "
                    "and details. Use both what you SEE and what you HEAR to fill in "
                    "spoken_defects and all other fields."
                )

            hero_frame_instruction = ""
            if has_frames:
                hero_frame_instruction = (
                    f"  hero_frame_indices (array of integers): 0-based indices into the "
                    f"{n_frames} extracted frames (valid range: 0 to {n_frames - 1}). "
                    f"Pick 2-3 frames that BEST show THIS specific item.\n"
                )
            else:
                hero_frame_instruction = (
                    "  hero_frame_indices (array of integers): estimated 0-based frame "
                    "indices (assuming 1 frame every 2 seconds) that best show this item. "
                    "Pick 2-3.\n"
                )

            prompt = (
                "You are an expert product analyst for a resale marketplace.\n\n"
                "Analyze this video showing one or more items. The user is speaking about each item, "
                "describing what it is, its condition, and any defects.\n\n"
                "For each distinct item you see AND/OR hear described, return a JSON array of objects. "
                "Each object must have:\n"
                "  name_guess (string): best guess at product name/model\n"
                "  category (string): one of electronics, clothing, accessories, home, sports, toys, books, tools, automotive, other\n"
                "  likely_specs (object): spec names mapped to values like brand, model, color, storage\n"
                "  visible_defects (array): each element is an object with keys 'description' (string) and 'severity' (string: minor/moderate/major)\n"
                "  spoken_defects (array): same format as visible_defects, for defects the user mentions verbally\n"
                "  accessories_included (array of strings)\n"
                "  accessories_missing (array of strings)\n"
                "  confidence (float 0-1)\n"
                + hero_frame_instruction
                + "  segment_start_sec (float): when this item first appears in the video\n"
                "  segment_end_sec (float): when the camera moves away from this item\n\n"
                + transcript_block
                + "\n\nReturn ONLY a valid JSON array. No markdown fences. No extra text."
            )

            video_file = await _upload_video_and_wait(client, video_path, key_index=kidx)

            print(f"[GEMINI] [Key {kidx + 1}] Analyzing video with {GEMINI_MODEL}...")
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=[video_file, prompt],
            )

            raw = response.text.strip()
            print(f"[GEMINI] [Key {kidx + 1}] Raw response ({len(raw)} chars): {raw[:500]}{'...' if len(raw) > 500 else ''}")
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            items_data = json.loads(raw)

            print(f"[GEMINI] Parsed {len(items_data)} items from response")

            cards = _parse_items_data(items_data, frame_paths or [])
            for card in cards:
                print(f"[GEMINI]   → {card.name_guess} ({card.category.value}, confidence: {card.confidence:.0%}, defects: {len(card.all_defects)})")
            return cards

        except Exception as exc:
            print(f"[GEMINI] ✗ Video analysis FAILED: {exc}")
            import traceback
            traceback.print_exc()
            if settings.demo_mode:
                print(f"[GEMINI] Falling back to mock data (demo_mode=True)")
                return self._mock_analyze(frame_paths)
            raise

    async def extract_and_analyze(
        self,
        video_path: str,
        extract_frames_fn,
        on_frames_done=None,
        on_transcript_done=None,
        on_analysis_done=None,
    ) -> tuple[list[str], str, list[ItemCard]]:
        """Fused extraction+analysis: uploads the video once, then runs frame
        extraction, transcription, and video analysis concurrently.

        Upload is the bottleneck (~80-90s for a 160MB file). By uploading once
        and sharing the file reference, we cut the fused stage time roughly in
        half:
          - Upload: single upload on primary key, ~40-50s
          - Task A (frames): local ffmpeg, ~2-4s  (overlaps with upload)
          - Task B (transcript): Gemini inference, ~6-10s (after upload)
          - Task C (analysis): Gemini inference, ~6-10s  (after upload)
        Total wall time ≈ upload + max(B, C) instead of max(upload+B, upload+C).

        extract_frames_fn: an async callable (video_path) -> list[str] of frame paths.
        on_*_done: optional async callbacks for emitting progress events.
        """
        import time as _time

        print(f"[FUSED] ═══ Starting concurrent extraction + analysis ═══")
        t0 = _time.time()

        # ── Check if transcript + analysis are pre-computed ──
        content_hash = await asyncio.to_thread(_file_content_hash, video_path)
        cached_t = _transcript_cache.get(content_hash)
        cached_a = _analysis_cache.get(content_hash)

        if cached_t is not None and cached_a is not None:
            frame_paths = await extract_frames_fn(video_path)
            items = _parse_items_data(cached_a, frame_paths)
            items = assign_hero_frames(items, frame_paths)
            for card in items:
                card.raw_transcript_segment = _extract_segment_transcript(
                    cached_t, card.segment_start_sec, card.segment_end_sec
                )
            elapsed = _time.time() - t0
            print(f"[FUSED] ✓ Full cache hit: {len(items)} items, {len(frame_paths)} frames, "
                  f"{len(cached_t)} chars transcript in {elapsed:.1f}s")
            if on_frames_done:
                await on_frames_done(frame_paths)
            if on_transcript_done:
                await on_transcript_done(cached_t)
            if on_analysis_done:
                await on_analysis_done(items)
            return frame_paths, cached_t, items

        client, kidx = self._get_primary_client()

        frame_task = asyncio.create_task(self._fused_extract_frames(extract_frames_fn, video_path))
        upload_task = asyncio.create_task(
            _upload_video_and_wait(client, video_path, key_index=kidx)
        )
        print(f"[FUSED] Uploading video once (Key {kidx + 1}) while extracting frames locally...")

        video_file = await upload_task
        upload_elapsed = _time.time() - t0
        print(f"[FUSED] ✓ Upload complete in {upload_elapsed:.1f}s — now running transcription + analysis concurrently")

        transcript_task = asyncio.create_task(
            self._fused_transcribe_with_file(client, video_file, kidx)
        )
        analysis_task = asyncio.create_task(
            self._fused_analyze_with_file(client, video_file, kidx, video_path)
        )

        frame_paths: list[str] = []
        transcript: str = ""
        items: list[ItemCard] = []
        errors: list[str] = []

        results = await asyncio.gather(
            frame_task, transcript_task, analysis_task, return_exceptions=True
        )

        # --- Unpack frame extraction ---
        if isinstance(results[0], BaseException):
            print(f"[FUSED] ✗ Frame extraction failed: {results[0]}")
            errors.append(f"frames: {results[0]}")
        else:
            frame_paths = results[0]
            print(f"[FUSED] ✓ Frames: {len(frame_paths)} extracted in {_time.time()-t0:.1f}s")
            if on_frames_done:
                await on_frames_done(frame_paths)

        # --- Unpack transcription ---
        if isinstance(results[1], BaseException):
            print(f"[FUSED] ✗ Transcription failed: {results[1]}")
            errors.append(f"transcript: {results[1]}")
        else:
            transcript = results[1]
            _transcript_cache[content_hash] = transcript
            print(f"[FUSED] ✓ Transcript: {len(transcript)} chars in {_time.time()-t0:.1f}s")
            if on_transcript_done:
                await on_transcript_done(transcript)

        # --- Unpack analysis (returns (cards, raw_data) tuple) ---
        if isinstance(results[2], BaseException):
            print(f"[FUSED] ✗ Analysis failed: {results[2]}")
            errors.append(f"analysis: {results[2]}")

            if transcript:
                print(f"[FUSED] Retrying analysis with transcript as fallback...")
                try:
                    items = await self.analyze_video(
                        video_path=video_path,
                        transcript=transcript,
                        frame_paths=frame_paths,
                    )
                    print(f"[FUSED] ✓ Fallback analysis succeeded: {len(items)} items")
                except Exception as retry_exc:
                    print(f"[FUSED] ✗ Fallback analysis also failed: {retry_exc}")
                    if settings.demo_mode:
                        items = self._mock_analyze(frame_paths)
                    else:
                        raise results[2] from retry_exc
            elif settings.demo_mode:
                items = self._mock_analyze(frame_paths)
            else:
                raise results[2]
        else:
            items, items_data_raw = results[2]
            _analysis_cache[content_hash] = items_data_raw
            print(f"[FUSED] ✓ Analysis: {len(items)} items in {_time.time()-t0:.1f}s")

        # --- Post-merge enrichment ---
        if items and frame_paths:
            items = assign_hero_frames(items, frame_paths)
            print(f"[FUSED] ✓ Hero frames assigned to {len(items)} items")

        if items and transcript:
            for card in items:
                card.raw_transcript_segment = _extract_segment_transcript(
                    transcript, card.segment_start_sec, card.segment_end_sec
                )

        if on_analysis_done:
            await on_analysis_done(items)

        elapsed = _time.time() - t0
        print(f"[FUSED] ═══ Fused stage complete in {elapsed:.1f}s — "
              f"{len(items)} items, {len(frame_paths)} frames, {len(transcript)} chars transcript ═══")
        if errors:
            print(f"[FUSED] ⚠ Partial failures: {'; '.join(errors)}")

        return frame_paths, transcript, items

    async def _fused_extract_frames(self, extract_fn, video_path: str) -> list[str]:
        return await extract_fn(video_path)

    async def _fused_transcribe(self, video_path: str) -> str:
        return await self.transcribe_from_video(video_path)

    async def _fused_analyze(self, video_path: str) -> list[ItemCard]:
        return await self.analyze_video(video_path=video_path)

    async def _fused_transcribe_with_file(
        self, client: genai.Client, video_file, key_index: int
    ) -> str:
        """Run transcription using an already-uploaded file reference."""
        print(f"[GEMINI] [Key {key_index + 1}] Transcribing speech from video...")
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=[
                video_file,
                "Transcribe all spoken words in this video exactly as said. "
                "Return the raw transcript text. If there is no speech at all, "
                "return the single word EMPTY.",
            ],
        )
        text = response.text.strip()
        result = "" if text == "EMPTY" else text
        print(f"[GEMINI] [Key {key_index + 1}] Transcript ({len(result)} chars): "
              f"{result[:300]}{'...' if len(result) > 300 else ''}")
        return result

    async def _fused_analyze_with_file(
        self, client: genai.Client, video_file, key_index: int, video_path: str
    ) -> tuple[list[ItemCard], list[dict]]:
        """Run analysis using an already-uploaded file reference.
        Returns (parsed ItemCards, raw items_data dicts) so caller can cache the raw data."""
        transcript_block = (
            "IMPORTANT: Listen carefully to ALL speech in the video's audio track. "
            "The user describes each item verbally, mentioning defects, condition, "
            "and details. Use both what you SEE and what you HEAR to fill in "
            "spoken_defects and all other fields."
        )
        hero_frame_instruction = (
            "  hero_frame_indices (array of integers): estimated 0-based frame "
            "indices (assuming 1 frame every 2 seconds) that best show this item. "
            "Pick 2-3.\n"
        )
        prompt = (
            "You are an expert product analyst for a resale marketplace.\n\n"
            "Analyze this video showing one or more items. The user is speaking about each item, "
            "describing what it is, its condition, and any defects.\n\n"
            "For each distinct item you see AND/OR hear described, return a JSON array of objects. "
            "Each object must have:\n"
            "  name_guess (string): best guess at product name/model\n"
            "  category (string): one of electronics, clothing, accessories, home, sports, toys, books, tools, automotive, other\n"
            "  likely_specs (object): spec names mapped to values like brand, model, color, storage\n"
            "  visible_defects (array): each element is an object with keys 'description' (string) and 'severity' (string: minor/moderate/major)\n"
            "  spoken_defects (array): same format as visible_defects, for defects the user mentions verbally\n"
            "  accessories_included (array of strings)\n"
            "  accessories_missing (array of strings)\n"
            "  confidence (float 0-1)\n"
            + hero_frame_instruction
            + "  segment_start_sec (float): when this item first appears in the video\n"
            "  segment_end_sec (float): when the camera moves away from this item\n\n"
            + transcript_block
            + "\n\nReturn ONLY a valid JSON array. No markdown fences. No extra text."
        )

        print(f"[GEMINI] [Key {key_index + 1}] Analyzing video with {GEMINI_MODEL}...")
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=[video_file, prompt],
        )

        raw = response.text.strip()
        print(f"[GEMINI] [Key {key_index + 1}] Raw response ({len(raw)} chars): "
              f"{raw[:500]}{'...' if len(raw) > 500 else ''}")
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        items_data = json.loads(raw)

        print(f"[GEMINI] Parsed {len(items_data)} items from response")
        cards = _parse_items_data(items_data, [])
        for card in cards:
            print(f"[GEMINI]   → {card.name_guess} ({card.category.value}, "
                  f"confidence: {card.confidence:.0%}, defects: {len(card.all_defects)})")
        return cards, items_data

    async def generate_listing(self, item_card: ItemCard, comp_prices: list[float] | None = None) -> dict:
        # ── Cache check ──
        cache_key = item_card.name_guess
        if cache_key in _listing_cache:
            print(f"[GEMINI] generate_listing cache hit: \"{cache_key}\"")
            return _listing_cache[cache_key]

        if settings.demo_mode and not settings.gemini_api_key:
            return self._mock_listing(item_card)

        import time as _time

        try:
            client, key_idx, key_total = self._get_client_with_id()
            print(f"[GEMINI] [Key {key_idx}/{key_total}] generate_listing(\"{item_card.name_guess}\") — starting...")
            t0 = _time.time()
            defects_str = "; ".join(d.description for d in item_card.all_defects) or "None"

            price_anchor = ""
            if comp_prices:
                sorted_prices = sorted(comp_prices)
                median_p = sorted_prices[len(sorted_prices) // 2]
                low_p, high_p = sorted_prices[0], sorted_prices[-1]
                price_anchor = (
                    f"\nMarket data (used/pre-owned comparable sales):\n"
                    f"  Median resale price: ${median_p:.2f}\n"
                    f"  Price range: ${low_p:.2f} - ${high_p:.2f}\n"
                    f"  Number of comps: {len(comp_prices)}\n"
                    f"YOUR PRICES MUST BE WITHIN THIS RANGE. "
                    f"price_strategy should be near the median (${median_p:.2f}). "
                    f"Do NOT use retail/new prices.\n"
                )

            prompt = (
                "Generate a marketplace listing for this used/pre-owned item.\n\n"
                "Item: " + item_card.name_guess + "\n"
                "Category: " + item_card.category.value + "\n"
                "Specs: " + json.dumps(item_card.likely_specs) + "\n"
                "Condition: " + item_card.condition_label + "\n"
                "Defects: " + defects_str + "\n"
                + price_anchor + "\n"
                "Return JSON with: title (string max 80 chars), description (string), "
                "price_strategy (float — your recommended asking price based on market data), "
                "price_min (float — lowest reasonable price), price_max (float — highest reasonable price), "
                "condition_summary (string), defects_disclosure (string), "
                "shipping_policy (string: standard or expedited).\n\n"
                "Return ONLY valid JSON, no markdown fences."
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=[prompt],
            )

            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(raw)
            elapsed = _time.time() - t0
            print(f"[GEMINI] [Key {key_idx}/{key_total}] generate_listing(\"{item_card.name_guess}\") — done in {elapsed:.1f}s — title: \"{result.get('title', '?')[:50]}\"")
            _listing_cache[cache_key] = result
            return result

        except Exception as exc:
            print(f"[GEMINI] generate_listing(\"{item_card.name_guess}\") — FAILED: {exc}")
            logger.exception("Gemini listing generation failed")
            if settings.demo_mode:
                return self._mock_listing(item_card)
            raise

    async def reason_about_route(self, item_card: ItemCard, bids: list) -> str:
        if settings.demo_mode and not settings.gemini_api_key:
            return f"Based on market analysis, selling {item_card.name_guess} as-is offers the best value recovery with minimal effort."

        try:
            client = self._get_client()
            bids_summary = "\n".join(
                f"- {b.route_type.value}: est. ${b.estimated_value:.2f}, effort={b.effort.value}, speed={b.speed.value}, confidence={b.confidence:.0%}"
                for b in bids
            )
            defects_str = "; ".join(d.description for d in item_card.all_defects) or "None"
            prompt = (
                "You are a concierge explaining why a particular route was chosen.\n\n"
                "Item: " + item_card.name_guess + " (" + item_card.category.value + ")\n"
                "Condition: " + item_card.condition_label + "\n"
                "Defects: " + defects_str + "\n\n"
                "Route bids:\n" + bids_summary + "\n\n"
                "Explain in 2-3 sentences why the winning route is best for recovering max value with min effort."
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=[prompt],
            )
            return response.text.strip()

        except Exception:
            logger.exception("Gemini route reasoning failed")
            return f"Recommended route selected for {item_card.name_guess} based on value and effort analysis."

    async def transcribe_from_video(self, video_path: str, key_index: int | None = None) -> str:
        """Transcribe speech from video using Gemini.

        When key_index is provided, that specific key is used for the upload and
        inference (enabling concurrent uploads on different keys). When omitted,
        the secondary client is used by default so transcription and analysis can
        run in parallel on different keys.
        """
        if settings.demo_mode and not settings.gemini_api_key:
            return "This is a demo item. It's in good condition overall with some minor scratches on the back."

        try:
            if key_index is not None:
                if key_index >= len(self._clients):
                    key_index = 0
                client, kidx = self._clients[key_index], key_index
            else:
                client, kidx = self._get_secondary_client()

            video_file = await _upload_video_and_wait(client, video_path, key_index=kidx)

            print(f"[GEMINI] [Key {kidx + 1}] Transcribing speech from video...")
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=[
                    video_file,
                    "Transcribe all spoken words in this video exactly as said. Return the raw transcript text. If there is no speech at all, return the single word EMPTY.",
                ],
            )
            text = response.text.strip()
            result = "" if text == "EMPTY" else text
            print(f"[GEMINI] [Key {kidx + 1}] Transcript ({len(result)} chars): {result[:300]}{'...' if len(result) > 300 else ''}")
            return result

        except Exception as exc:
            print(f"[GEMINI] ✗ Transcription FAILED: {exc}")
            import traceback
            traceback.print_exc()
            return ""

    async def search_live_comps(
        self,
        item_name: str,
        category: str = "",
        condition: str = "",
    ) -> list[ComparableListing]:
        if not settings.gemini_api_key:
            return self._mock_comps(item_name)

        import time as _time

        try:
            client, key_idx, key_total = self._get_client_with_id()
            condition_hint = f" in {condition} condition" if condition else ""
            print(f"[GEMINI] [Key {key_idx}/{key_total}] search_live_comps(\"{item_name}\"{condition_hint}) — starting...")
            t0 = _time.time()
            prompt = (
                'Search for "' + item_name + '"' + condition_hint + " currently listed for RESALE (used/pre-owned) online. "
                "Find 6-10 real active listings from RESALE marketplaces like eBay, Swappa, "
                "Facebook Marketplace, OfferUp, Poshmark, Craigslist.\n\n"
                "CRITICAL RULES:\n"
                "- Only include USED, PRE-OWNED, or OPEN BOX listings from individual sellers\n"
                "- EXCLUDE brand-new retail listings, Amazon retail prices, and official store prices\n"
                "- EXCLUDE bundles, multi-packs, or listings that include extra items\n"
                "- EXCLUDE listings for a different model/version of the product\n"
                "- match_score must reflect how closely the listing matches the EXACT product "
                "(same brand, model, size, color). Penalize heavily for wrong model/version.\n\n"
                "For each listing, return a JSON array of objects with these exact fields:\n"
                "- platform: marketplace name lowercase (ebay, swappa, facebook, offerup, poshmark, craigslist, other)\n"
                "- title: the exact listing title as shown\n"
                "- price: the listed price as a float in USD (0 if not shown)\n"
                "- condition: condition as listed (e.g. Used - Good, Like New, For Parts, etc.)\n"
                "- url: the direct URL to the listing page\n"
                "- image_url: the URL of the listing main thumbnail if visible, otherwise empty string\n"
                '- shipping: shipping cost info (e.g. "FREE", "$5.99", "Local pickup")\n'
                '- match_score: similarity to "' + item_name + '" as integer 0-100 '
                "(100 = exact same product in same condition, 70 = same product different condition, "
                "below 60 = different model/version)\n\n"
                "Important: include REAL currently active RESALE listings with actual prices. "
                "Prefer listings with images. Return ONLY valid JSON array, no markdown."
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            elapsed = _time.time() - t0

            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

            listings_data = json.loads(raw)
            results: list[ComparableListing] = []
            for item in listings_data:
                results.append(ComparableListing(
                    platform=item.get("platform", "unknown"),
                    title=item.get("title", ""),
                    price=float(item.get("price", 0)),
                    shipping=str(item.get("shipping", "")),
                    condition=item.get("condition", ""),
                    url=item.get("url", ""),
                    image_url=item.get("image_url", ""),
                    match_score=float(item.get("match_score", 70)),
                ))
            prices = [r.price for r in results if r.price > 0]
            avg_price = sum(prices) / len(prices) if prices else 0
            print(f"[GEMINI] [Key {key_idx}/{key_total}] search_live_comps(\"{item_name}\") — done in {elapsed:.1f}s — {len(results)} comps, avg ${avg_price:.0f}")
            return results

        except Exception as exc:
            print(f"[GEMINI] [Key ?/?] search_live_comps(\"{item_name}\") — FAILED: {exc}")
            logger.exception("Gemini live comp search failed for '%s'", item_name)
            return self._mock_comps(item_name)

    async def search_platform(
        self,
        item_name: str,
        platforms: list[str],
        condition: str = "",
    ) -> list[ComparableListing]:
        """Search specific platforms only — faster than searching all at once."""
        # ── Cache check ──
        cache_key = f"{item_name}|{condition}|{','.join(sorted(platforms))}"
        if cache_key in _search_cache:
            cached = _search_cache[cache_key]
            print(f"[GEMINI] search_platform cache hit: \"{item_name}\" [{', '.join(platforms)}] → {len(cached)} results")
            return cached

        if not settings.gemini_api_key:
            return []

        import time as _time
        platform_str = ", ".join(platforms)

        try:
            client, key_idx, key_total = self._get_client_with_id()
            condition_hint = f" in {condition} condition" if condition else ""
            print(f"[GEMINI] [Key {key_idx}/{key_total}] search_platform(\"{item_name}\", [{platform_str}]) — starting...")
            t0 = _time.time()
            prompt = (
                f'Search for "{item_name}"{condition_hint} currently listed for RESALE (used/pre-owned) on '
                f'{platform_str}.\n\n'
                f'Find 2-4 real active RESALE listings from these specific platforms: {platform_str}.\n\n'
                "CRITICAL: Only include USED, PRE-OWNED, or OPEN BOX listings. "
                "EXCLUDE brand-new retail, official store prices, bundles, and different models.\n\n"
                "For each listing, return a JSON array of objects with these exact fields:\n"
                "- platform: marketplace name lowercase\n"
                "- title: the exact listing title as shown\n"
                "- price: the listed price as a float in USD (0 if not shown)\n"
                "- condition: condition as listed\n"
                "- url: the direct URL to the listing page\n"
                "- image_url: the URL of the listing main thumbnail if visible, otherwise empty string\n"
                '- shipping: shipping cost info (e.g. "FREE", "$5.99", "Local pickup")\n'
                f'- match_score: similarity to "{item_name}" as integer 0-100 '
                "(100 = exact product, below 60 = different model)\n\n"
                "Return ONLY currently active real RESALE listings with actual prices. "
                "Return ONLY valid JSON array, no markdown."
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            elapsed = _time.time() - t0

            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

            listings_data = json.loads(raw)
            results: list[ComparableListing] = []
            for item in listings_data:
                results.append(ComparableListing(
                    platform=item.get("platform", "unknown"),
                    title=item.get("title", ""),
                    price=float(item.get("price", 0)),
                    shipping=str(item.get("shipping", "")),
                    condition=item.get("condition", ""),
                    url=item.get("url", ""),
                    image_url=item.get("image_url", ""),
                    match_score=float(item.get("match_score", 70)),
                ))
            print(f"[GEMINI] [Key {key_idx}/{key_total}] search_platform(\"{item_name}\", [{platform_str}]) — done in {elapsed:.1f}s — {len(results)} results")
            _search_cache[cache_key] = results
            return results

        except Exception as exc:
            print(f"[GEMINI] search_platform(\"{item_name}\", [{platform_str}]) — FAILED: {exc}")
            return []

    @staticmethod
    def _mock_comps(query: str) -> list[ComparableListing]:
        return [
            ComparableListing(platform="ebay", title=f"{query} - Excellent Condition", price=89.99, shipping="FREE", condition="Like New", url="", match_score=94),
            ComparableListing(platform="swappa", title=f"{query} - Good Condition", price=82.50, shipping="FREE", condition="Good", url="", match_score=87),
            ComparableListing(platform="facebook", title=f"{query} - Used", price=65.00, shipping="Local pickup", condition="Good", url="", match_score=82),
            ComparableListing(platform="offerup", title=f"{query} - Great Deal", price=70.00, shipping="$7.99", condition="Good", url="", match_score=78),
            ComparableListing(platform="ebay", title=f"{query} - For Parts/Repair", price=35.00, shipping="$8.99", condition="Fair", url="", match_score=65),
        ]

    def _mock_analyze(self, frame_paths: list[str] | None = None) -> list[ItemCard]:
        frames = frame_paths or []
        hero_urls = [_frame_path_to_url(p) for p in frames[:2]] if frames else []
        return [
            ItemCard(
                name_guess="Apple AirPods Pro (2nd Gen)",
                category=ItemCategory.ELECTRONICS,
                likely_specs={"brand": "Apple", "model": "AirPods Pro 2", "color": "White", "connectivity": "Bluetooth 5.3"},
                visible_defects=[DefectSignal(description="Minor scratches on charging case", source="visual", severity="minor")],
                spoken_defects=[],
                accessories_included=["Charging case", "USB-C cable"],
                accessories_missing=["Extra ear tips"],
                confidence=0.92,
                hero_frame_paths=hero_urls,
                all_frame_paths=frames,
                segment_start_sec=0.0,
                segment_end_sec=30.0,
            ),
        ]

    def _mock_listing(self, item_card: ItemCard) -> dict:
        return {
            "title": f"{item_card.name_guess} - {item_card.condition_label} Condition",
            "description": f"Selling my {item_card.name_guess}. {item_card.condition_label} condition. All original accessories included.",
            "price_strategy": 85.0,
            "price_min": 70.0,
            "price_max": 100.0,
            "condition_summary": item_card.condition_label,
            "defects_disclosure": "; ".join(d.description for d in item_card.all_defects) or "No notable defects.",
            "shipping_policy": "standard",
        }
