"""FastAPI server for ReRoute v2 — dual WebSocket endpoints + REST.

Routes:
  POST /api/upload              — Video upload, starts pipeline
  GET  /api/jobs/{jobId}        — Job status + metadata
  GET  /api/jobs/{jobId}/agents — All agent states for a job

WebSocket:
  /ws/{jobId}/events            — JSON text frames (agent lifecycle events)
  /ws/{jobId}/screenshots       — Binary frames (CDP screenshots)

Architecture (from streaming-server-intake-review.md):
  Three async loops, three files, one process, one event loop.
  - intake.py:     ffmpeg pipe + Gemini batch analysis → ItemCards
  - streaming.py:  CDP capture loops → frame_store dict
  - server.py:     FastAPI + WS endpoints, reads from frame_store + event queue

Interface with orchestrator (stubbed, Person 1 builds):
  orchestrator.events               — asyncio.Queue[dict] of agent lifecycle events
  orchestrator.get_browser(agent_id) — Returns Browser-Use Browser instance
  orchestrator.start_pipeline(job_id, items) — Kicks off agent spawning
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiofiles
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import settings
from backend.models.item_card import ItemCard
from backend.models.job import Job, JobStatus
from backend.models.conversation import ConversationThread
from backend.streaming import (
    encode_binary_frame,
    get_all_agent_ids,
    get_frame_for_delivery,
)
from backend.debug_trace import swarma_line, swarma_ws_out

logger = logging.getLogger("swarmsell.server")

# In-memory thread store for conversation endpoints.
# Mirrors the store.py pattern but scoped to the v2 server.
_threads: dict[str, ConversationThread] = {}


# ── Orchestrator ──────────────────────────────────────────────────────────────
# Try to load the real Browser-Use orchestrator with playbooks.
# Falls back to a lightweight stub if imports fail.

def _create_orchestrator():
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from orchestrator import Orchestrator
        import playbooks as _pb_init  # noqa: F841 — triggers register_playbook calls
        from orchestrator import PLAYBOOKS
        logger.info("Real orchestrator loaded, playbooks: %s", list(PLAYBOOKS.keys()))
        swarma_line("server", "orchestrator_real", playbooks=list(PLAYBOOKS.keys()))

        orch = Orchestrator()

        if not hasattr(orch, 'get_agent_states'):
            def _get_agent_states(job_id=None):
                return {a.agent_id: a.__dict__ if hasattr(a, '__dict__') else a
                        for a in orch.get_active_agents()}
            orch.get_agent_states = _get_agent_states

        return orch
    except Exception as exc:
        logger.warning("Real orchestrator unavailable (%s), using stub", exc)
        swarma_line("server", "orchestrator_stub_fallback", error=str(exc))
        return _OrchestratorStub()


class _OrchestratorStub:
    """Fallback stub when real orchestrator can't be imported."""

    def __init__(self):
        self.events: asyncio.Queue = asyncio.Queue()
        self._agents: dict[str, dict] = {}

    async def start_pipeline(self, job_id: str, items: list[ItemCard]) -> None:
        platforms = ["facebook", "depop", "amazon"]
        for item in items:
            for platform in platforms:
                agent_id = f"{platform}-research-{item.item_id}"
                self._agents[agent_id] = {
                    "agent_id": agent_id, "item_id": item.item_id,
                    "platform": platform, "phase": "research",
                    "status": "queued", "task": f"Research {item.name_guess} on {platform}",
                }
                await self.events.put({
                    "type": "agent:spawn",
                    "data": {
                        "agent_id": agent_id, "agentId": agent_id,
                        "item_id": item.item_id, "platform": platform,
                        "phase": "research", "status": "queued",
                        "task": self._agents[agent_id]["task"],
                    },
                })
        swarma_line("orchestrator.stub", "spawned", job_id=job_id, agents_n=len(self._agents))

    def get_agent_states(self, job_id: str) -> dict[str, dict]:
        return dict(self._agents)

    def release_research(self):
        pass


orchestrator = _create_orchestrator()


# ── Facebook Inbox Poller (Concierge) ─────────────────────────────────────────
# Lazy-loaded to avoid import errors if fb_inbox_poller deps are missing.

_fb_poller = None  # type: ignore


def _get_fb_poller():
    global _fb_poller
    if _fb_poller is None:
        try:
            import sys as _sys2
            _sys2.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from fb_inbox_poller import FBInboxPoller
            _fb_poller = FBInboxPoller(broadcast_fn=ws_manager.broadcast_event)
            swarma_line("server", "fb_poller_created")
        except Exception as exc:
            logger.warning("FB poller unavailable: %s", exc)
            swarma_line("server", "fb_poller_unavailable", error=str(exc))
    return _fb_poller


# ── In-Memory Job Store ───────────────────────────────────────────────────────
# Simple dict for hackathon. No persistence needed.

_jobs: dict[str, Job] = {}
_job_items: dict[str, list[ItemCard]] = {}
# Intake-stage JPEGs (job_id → frame index str → bytes); served at /api/jobs/.../intake-frames/...
_intake_frame_store: dict[str, dict[str, bytes]] = {}


# ── WebSocket Connection Manager ──────────────────────────────────────────────
# Extended from v1 (server.py:127-159) for dual WS endpoints.


class ConnectionManager:
    """Manages WebSocket connections per job, for both events and screenshots."""

    def __init__(self) -> None:
        self._events: dict[str, set[WebSocket]] = {}
        self._screenshots: dict[str, set[WebSocket]] = {}

    async def connect_events(self, job_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._events.setdefault(job_id, set()).add(ws)
        n = len(self._events[job_id])
        logger.info("Events WS connected for job %s (%d clients)", job_id, n)
        swarma_line("ws.events", "client_connected", job_id=job_id, clients_now=n)

    async def connect_screenshots(self, job_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._screenshots.setdefault(job_id, set()).add(ws)
        n = len(self._screenshots[job_id])
        logger.info("Screenshots WS connected for job %s (%d clients)", job_id, n)
        swarma_line("ws.screenshots", "client_connected", job_id=job_id, clients_now=n)

    def disconnect_events(self, job_id: str, ws: WebSocket) -> None:
        if job_id in self._events:
            self._events[job_id].discard(ws)
            rem = len(self._events[job_id])
            swarma_line("ws.events", "client_disconnected", job_id=job_id, clients_now=rem)
            if not self._events[job_id]:
                del self._events[job_id]

    def disconnect_screenshots(self, job_id: str, ws: WebSocket) -> None:
        if job_id in self._screenshots:
            self._screenshots[job_id].discard(ws)
            rem = len(self._screenshots[job_id])
            swarma_line("ws.screenshots", "client_disconnected", job_id=job_id, clients_now=rem)
            if not self._screenshots[job_id]:
                del self._screenshots[job_id]

    async def broadcast_event(self, job_id: str, event: dict) -> None:
        """Send a JSON event to all event WS clients for a job."""
        # Capture for demo recording if enabled
        from demo_capture import capture_event, CAPTURE_ENABLED
        if CAPTURE_ENABLED:
            capture_event(event)

        connections = self._events.get(job_id)
        n = len(connections) if connections else 0
        swarma_ws_out(job_id, event, client_count=n)
        if not connections:
            return
        stale: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(event)
            except Exception as exc:
                logger.warning("Event WS send failed for job %s: %s", job_id, exc)
                stale.append(ws)
        for ws in stale:
            connections.discard(ws)

    async def broadcast_screenshot(self, job_id: str, binary_frame: bytes) -> None:
        """Send a binary screenshot frame to all screenshot WS clients for a job."""
        connections = self._screenshots.get(job_id)
        if not connections:
            return
        stale: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_bytes(binary_frame)
            except Exception as exc:
                logger.warning("Screenshot WS send failed for job %s: %s", job_id, exc)
                stale.append(ws)
        for ws in stale:
            connections.discard(ws)

    def has_screenshot_clients(self, job_id: str) -> bool:
        return bool(self._screenshots.get(job_id))


ws_manager = ConnectionManager()


# ── Background Tasks ──────────────────────────────────────────────────────────


async def _event_drain_loop(job_id: str):
    """Drain agent events from orchestrator queue and broadcast to WS clients.

    Runs as a background task for the lifetime of the pipeline.
    Pattern confirmed in streaming-server-intake-review.md:
      while True: event = await orchestrator.events.get(); broadcast(event)

    Also populates frame_store from agent:screenshot events so the binary WS
    screenshot pipeline works even when CDP screencast fails.
    """
    logger.info("Event drain loop started for job %s", job_id)
    swarma_line("pipeline", "event_drain_loop_started", job_id=job_id)
    try:
        while True:
            event = await orchestrator.events.get()
            # Real orchestrator emits AgentEvent pydantic objects; stub emits dicts
            if hasattr(event, 'model_dump'):
                event_dict = {"type": event.type, "data": event.data if isinstance(event.data, dict) else {}}
                if hasattr(event, 'agent_id') and event.agent_id:
                    event_dict["data"]["agent_id"] = event.agent_id
                    event_dict["data"]["agentId"] = event.agent_id
            elif isinstance(event, dict):
                event_dict = event
            else:
                event_dict = {"type": str(event), "data": {}}

            evt_type = event_dict.get("type")
            evt_data = event_dict.get("data", {})

            if evt_type == "agent:screenshot" and evt_data.get("screenshot_b64"):
                agent_id = evt_data.get("agent_id") or evt_data.get("agentId")
                if agent_id:
                    try:
                        import base64 as _b64
                        from backend.streaming import frame_store, FrameData
                        jpeg_bytes = _b64.b64decode(evt_data["screenshot_b64"])
                        frame_store[agent_id] = FrameData(jpeg=jpeg_bytes, ts=time.time())
                    except Exception:
                        pass

            swarma_line("orchestrator", "event_dequeued", job_id=job_id, type=evt_type)
            await ws_manager.broadcast_event(job_id, event_dict)
    except asyncio.CancelledError:
        logger.info("Event drain loop stopped for job %s", job_id)
        swarma_line("pipeline", "event_drain_loop_cancelled", job_id=job_id)
        raise


async def _screenshot_push_loop(job_id: str):
    """Push latest screenshots to all WS clients at a uniform rate.

    All agents are delivered at settings.screenshot_grid_delivery_fps (default 1 fps).
    No per-agent differentiation — the whole swarm is always live simultaneously.

    Uses frame_store (module-level dict in streaming.py) as the source.
    """
    interval = 1.0 / settings.screenshot_grid_delivery_fps
    last_sent: dict[str, float] = {}

    logger.info("Screenshot push loop started for job %s", job_id)
    swarma_line("pipeline", "screenshot_push_loop_started", job_id=job_id)
    try:
        while True:
            if not ws_manager.has_screenshot_clients(job_id):
                await asyncio.sleep(0.5)
                continue

            now = time.time()
            active_ids = get_all_agent_ids()
            for agent_id in active_ids:
                if now - last_sent.get(agent_id, 0) < interval:
                    continue
                try:
                    jpeg_bytes = get_frame_for_delivery(agent_id)
                    if jpeg_bytes is None:
                        continue

                    binary_frame = encode_binary_frame(agent_id, jpeg_bytes)
                    await ws_manager.broadcast_screenshot(job_id, binary_frame)
                    last_sent[agent_id] = now
                except Exception:
                    pass  # skip this agent's frame, don't kill the loop

            # Prune last_sent entries for agents no longer streaming
            stale_keys = [k for k in last_sent if k not in active_ids]
            for k in stale_keys:
                del last_sent[k]

            await asyncio.sleep(interval)

    except asyncio.CancelledError:
        logger.info("Screenshot push loop stopped for job %s", job_id)
        swarma_line("pipeline", "screenshot_push_loop_cancelled", job_id=job_id)
        raise


async def _run_pipeline(job_id: str, video_path: str):
    """Main pipeline coroutine: intake → orchestrator → streaming.

    Wrapped in try/except per eng review decision:
    on unhandled error, log, set job FAILED, emit error event, don't re-raise.
    """
    from backend.intake import streaming_analysis

    job = _jobs.get(job_id)
    if not job:
        swarma_line("pipeline", "run_pipeline_aborted_no_job", job_id=job_id)
        return

    swarma_line(
        "pipeline",
        "run_pipeline_start",
        job_id=job_id,
        video_path=video_path,
        job_status=str(job.status.value if hasattr(job.status, "value") else job.status),
    )

    # Start background loops
    event_drain = asyncio.create_task(_event_drain_loop(job_id))
    screenshot_push = asyncio.create_task(_screenshot_push_loop(job_id))

    try:
        # Phase 1: Intake — video → items (WS events match frontend useJob.js)
        job.status = JobStatus.ANALYZING
        job.touch()
        swarma_line("pipeline", "intake_phase_begin", job_id=job_id)
        await ws_manager.broadcast_event(job_id, {
            "type": "agent_started",
            "data": {"agent": "intake", "message": "Analyzing video — extracting audio and frames…"},
        })
        await ws_manager.broadcast_event(job_id, {
            "type": "job_updated",
            "data": {"status": JobStatus.ANALYZING.value},
        })

        items, timings, best_frames, transcript_text = await streaming_analysis(video_path, job_id)
        swarma_line(
            "pipeline",
            "streaming_analysis_done",
            job_id=job_id,
            items_n=len(items),
            best_frames_n=len(best_frames),
            transcript_len=len(transcript_text or ""),
            total_sec=round(timings.total_sec, 2) if timings else None,
        )

        if not items:
            job.status = JobStatus.FAILED
            job.error = "No items detected in video"
            job.touch()
            await ws_manager.broadcast_event(job_id, {
                "type": "agent_error",
                "data": {
                    "agent": "intake",
                    "error": "No items detected in video",
                    "message": "No items detected in video",
                },
            })
            swarma_line("pipeline", "intake_failed_no_items", job_id=job_id)
            return

        _intake_frame_store[job_id] = {}
        frame_urls_ordered: list[str] = []
        for idx, jpeg_bytes in best_frames:
            key = str(idx)
            _intake_frame_store[job_id][key] = jpeg_bytes
            frame_urls_ordered.append(f"/api/jobs/{job_id}/intake-frames/{key}")

        def _hero_urls(paths: list[str]) -> list[str]:
            out: list[str] = []
            for p in paths:
                if p.startswith("frame_"):
                    suffix = p[6:] if p.startswith("frame_") else p
                    out.append(f"/api/jobs/{job_id}/intake-frames/{suffix}")
                else:
                    out.append(p)
            return out

        t_txt = transcript_text or ""
        for item in items:
            item.hero_frame_paths = _hero_urls(item.hero_frame_paths)
            item.all_frame_paths = list(frame_urls_ordered)

        # Save per-item frames to disk so listing agents can access them.
        # Each item gets its OWN directory with ONLY its hero frames.
        listing_img_base = Path(settings.listing_images_dir)
        listing_img_base.mkdir(parents=True, exist_ok=True)
        for item in items:
            item_img_dir = listing_img_base / item.item_id
            item_img_dir.mkdir(parents=True, exist_ok=True)
            saved_paths: list[str] = []
            for i, url_path in enumerate(item.hero_frame_paths):
                frame_key = url_path.rsplit("/", 1)[-1] if "/" in url_path else url_path
                jpeg_data = _intake_frame_store[job_id].get(frame_key)
                if jpeg_data:
                    img_path = item_img_dir / f"photo_{i + 1}.jpg"
                    img_path.write_bytes(jpeg_data)
                    saved_paths.append(str(img_path.resolve()))
            item.listing_image_paths = saved_paths
            swarma_line("pipeline", "item_images_saved",
                        job_id=job_id, item=item.name_guess,
                        item_id=item.item_id, images_n=len(saved_paths))

        job.transcript_text = t_txt
        job.frame_paths = frame_urls_ordered
        job.item_ids = [item.item_id for item in items]
        job.touch()

        n_frames = len(frame_urls_ordered)
        if n_frames == 0:
            await ws_manager.broadcast_event(job_id, {
                "type": "agent_progress",
                "data": {
                    "agent": "intake",
                    "message": "Finalizing item details…",
                    "progress": 0.5,
                    "frame_paths": [],
                    "transcript_text": t_txt,
                },
            })
        else:
            for i in range(n_frames):
                await ws_manager.broadcast_event(job_id, {
                    "type": "agent_progress",
                    "data": {
                        "agent": "intake",
                        "message": f"Extracting frame {i + 1}/{n_frames}…",
                        "progress": 0.05 + 0.5 * (i + 1) / n_frames,
                        "frame_paths": frame_urls_ordered[: i + 1],
                        "transcript_text": t_txt,
                    },
                })
                await asyncio.sleep(0.28)

        await ws_manager.broadcast_event(job_id, {
            "type": "job_updated",
            "data": {"transcript_text": t_txt, "frame_paths": frame_urls_ordered},
        })

        _job_items[job_id] = items

        for item in items:
            await ws_manager.broadcast_event(job_id, {
                "type": "item_added",
                "data": item.model_dump(mode="json"),
            })

        elapsed_ms = int(timings.total_sec * 1000) if timings.total_sec else None
        await ws_manager.broadcast_event(job_id, {
            "type": "agent_completed",
            "data": {
                "agent": "intake",
                "message": f"Detected {len(items)} item(s)",
                "elapsed_ms": elapsed_ms,
                "frame_paths": frame_urls_ordered,
                "transcript_text": t_txt,
            },
        })

        # Phase 2: Orchestrator — spawn agents
        job.status = JobStatus.EXECUTING
        job.touch()
        await ws_manager.broadcast_event(job_id, {
            "type": "job_updated",
            "data": {"status": JobStatus.EXECUTING.value},
        })

        swarma_line("pipeline", "orchestrator_start_pipeline", job_id=job_id, items_n=len(items))

        # Start demo capture if DEMO_CAPTURE=true
        from demo_capture import start_capture, stop_capture, CAPTURE_ENABLED
        if CAPTURE_ENABLED:
            start_capture(job_id, items)

        # Use cached demo pipeline for known items, real pipeline otherwise
        from demo_cache import is_full_demo, run_cached_pipeline
        if is_full_demo(items) and not CAPTURE_ENABLED:
            swarma_line("pipeline", "using_demo_cache", job_id=job_id)
            await run_cached_pipeline(orchestrator, job_id, items)
        else:
            await orchestrator.start_pipeline(job_id, items)

        if CAPTURE_ENABLED:
            stop_capture()

        job.status = JobStatus.COMPLETED
        job.touch()
        await ws_manager.broadcast_event(job_id, {
            "type": "job_updated",
            "data": {"status": JobStatus.COMPLETED.value},
        })
        swarma_line("pipeline", "run_pipeline_completed", job_id=job_id)

    except Exception as exc:
        # Top-level pipeline guard (eng review decision: catch, log, FAIL, emit, don't re-raise)
        logger.exception("Pipeline failed for job %s: %s", job_id, exc)
        swarma_line("pipeline", "run_pipeline_exception", job_id=job_id, error=str(exc))
        job.status = JobStatus.FAILED
        job.error = str(exc)
        job.touch()
        await ws_manager.broadcast_event(job_id, {
            "type": "agent_error",
            "data": {
                "agent": "pipeline",
                "error": f"Pipeline failed: {exc}",
                "message": str(exc),
            },
        })

    finally:
        event_drain.cancel()
        screenshot_push.cancel()
        # Suppress CancelledError from the cancelled tasks
        for task in [event_drain, screenshot_push]:
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Free intake frames from memory — they're already saved to disk
        freed = _intake_frame_store.pop(job_id, None)
        if freed:
            swarma_line("pipeline", "intake_frames_freed",
                        job_id=job_id, frames_freed=len(freed))


# ── App Lifecycle ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    logger.info("SwarmSell server starting")
    swarma_line("server", "lifespan_startup", upload_dir=str(settings.upload_dir))
    yield
    # Kill the focus-guard osascript process on shutdown
    try:
        from orchestrator import _stop_focus_guard, _kill_focus_guard_sync
        await _stop_focus_guard()
        _kill_focus_guard_sync()
    except Exception:
        pass
    swarma_line("server", "lifespan_shutdown")
    logger.info("SwarmSell server shutting down")


app = FastAPI(title="SwarmSell", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Endpoints ────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "swarmsell"}


@app.get("/api/local-ip")
async def local_ip():
    """Return the server's LAN IP so the phone QR code works."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    logger.info("GET /api/local-ip → %s", ip)
    return {"ip": ip}


@app.get("/phone")
async def phone_chat_page():
    """Serve the buyer-chat HTML page for the phone demo."""
    chat_path = Path(__file__).resolve().parent.parent / "frontend" / "phone" / "chat.html"
    if not chat_path.exists():
        raise HTTPException(status_code=404, detail="Phone chat page not found")
    return Response(content=chat_path.read_text(), media_type="text/html")


class UploadResponse(BaseModel):
    job_id: str
    status: str


@app.post("/api/upload", response_model=UploadResponse)
async def upload_video(
    file: UploadFile | None = File(None),
    video: UploadFile | None = File(None),
):
    """Accept video upload, start the pipeline in the background.

    Deduplicates by content hash: if the same video was already uploaded,
    reuses the existing file instead of writing another copy.

    Multipart field may be ``file`` (frontend) or ``video`` (tests/CLI).
    """
    upload = file if (file and file.filename) else video
    if upload is None or not upload.filename:
        swarma_line("http", "upload_rejected", reason="no_file_field")
        raise HTTPException(status_code=400, detail="No file provided (use field 'file' or 'video')")

    job_id = uuid.uuid4().hex[:12]
    job = Job(job_id=job_id, status=JobStatus.UPLOADING)
    field = "file" if (file and file.filename) else "video"
    swarma_line(
        "http",
        "upload_accepted",
        job_id=job_id,
        multipart_field=field,
        filename=upload.filename,
    )

    # Read upload into memory and compute content hash
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(upload.filename or "video.mp4").suffix or ".mp4"

    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    while chunk := await upload.read(1024 * 1024):
        hasher.update(chunk)
        chunks.append(chunk)
    content_hash = hasher.hexdigest()[:16]
    total_bytes = sum(len(c) for c in chunks)
    swarma_line(
        "http",
        "upload_read_complete",
        job_id=job_id,
        bytes_total=total_bytes,
        content_hash_16=content_hash,
    )

    # Check for existing file with same hash
    hash_path = upload_dir / f"{content_hash}{ext}"
    if hash_path.exists():
        video_path = hash_path
        logger.info("Upload dedup: reusing %s for job %s", hash_path, job_id)
        swarma_line("http", "upload_dedup_reuse", job_id=job_id, path=str(video_path))
    else:
        video_path = hash_path
        async with aiofiles.open(video_path, "wb") as f:
            for chunk in chunks:
                await f.write(chunk)
        logger.info("Upload saved: %s (%d bytes) for job %s", video_path, sum(len(c) for c in chunks), job_id)
        swarma_line("http", "upload_written_new_file", job_id=job_id, path=str(video_path), bytes_total=total_bytes)

    job.video_path = str(video_path)
    job.status = JobStatus.EXTRACTING
    job.touch()
    _jobs[job_id] = job

    # Start pipeline in background
    asyncio.create_task(_run_pipeline(job_id, str(video_path)))
    swarma_line("http", "upload_pipeline_task_scheduled", job_id=job_id)

    return UploadResponse(job_id=job_id, status="processing")


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Job envelope for the UI: ``job`` plus ``items`` when intake has finished."""
    job = _jobs.get(job_id)
    if not job:
        swarma_line("http", "get_job", job_id=job_id, found=False)
        raise HTTPException(status_code=404, detail="Job not found")
    items = _job_items.get(job_id)
    swarma_line(
        "http",
        "get_job",
        job_id=job_id,
        found=True,
        job_status=str(job.status.value if hasattr(job.status, "value") else job.status),
        items_n=len(items) if items else 0,
    )
    payload: dict = {"job": job.model_dump(mode="json")}
    if items is not None:
        payload["items"] = [item.model_dump(mode="json") for item in items]
    return payload


@app.get("/api/jobs/{job_id}/intake-frames/{frame_idx}")
async def get_intake_frame(job_id: str, frame_idx: str):
    """Serve a single JPEG extracted during intake (path from ``frame_paths``)."""
    if not _jobs.get(job_id):
        swarma_line("http", "get_intake_frame", job_id=job_id, frame_idx=frame_idx, result="no_job")
        raise HTTPException(status_code=404, detail="Job not found")
    bucket = _intake_frame_store.get(job_id)
    if not bucket or frame_idx not in bucket:
        swarma_line(
            "http",
            "get_intake_frame",
            job_id=job_id,
            frame_idx=frame_idx,
            result="missing_frame",
            bucket_keys_n=len(bucket) if bucket else 0,
        )
        raise HTTPException(status_code=404, detail="Frame not found")
    return Response(content=bucket[frame_idx], media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/agents")
async def get_agents(job_id: str):
    """Get all agent states for a job. Used for WS reconnection state rebuild."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"agents": orchestrator.get_agent_states(job_id)}


@app.get("/api/jobs/{job_id}/items")
async def get_job_items(job_id: str):
    """Get full ItemCard details for a job."""
    items = _job_items.get(job_id)
    if items is None:
        raise HTTPException(status_code=404, detail="Job not found or no items yet")
    return [item.model_dump() for item in items]


@app.post("/api/jobs/{job_id}/start-research")
async def start_research(job_id: str):
    """User clicked Research — unblock the orchestrator gate."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    orchestrator.release_research()
    swarma_line("http", "start_research", job_id=job_id)
    return {"status": "research_started"}


# ── Inbox / Conversation Endpoints ────────────────────────────────────────────


class ReplyRequest(BaseModel):
    text: str


class BuyerChatRequest(BaseModel):
    text: str
    buyer_name: str = "Buyer"


def _get_threads_for_item(item_id: str) -> list[ConversationThread]:
    return [t for t in _threads.values() if t.item_id == item_id]


@app.get("/api/jobs/{job_id}/inbox")
async def get_inbox(job_id: str):
    """Get all conversation threads across all items for a job, ranked by seriousness."""
    job = _jobs.get(job_id)
    if not job:
        swarma_line("http", "get_inbox", job_id=job_id, found=False)
        raise HTTPException(status_code=404, detail="Job not found")
    all_threads = []
    for item_id in (job.item_ids or []):
        all_threads.extend(_get_threads_for_item(item_id))
    seriousness_order = {"high": 0, "medium": 1, "low": 2, "spam": 3}
    all_threads.sort(key=lambda t: seriousness_order.get(t.seriousness_score.value if hasattr(t.seriousness_score, 'value') else t.seriousness_score, 99))
    swarma_line("http", "get_inbox", job_id=job_id, threads_n=len(all_threads))
    return [t.model_dump(mode="json") for t in all_threads]


@app.post("/api/jobs/{job_id}/inbox/{thread_id}/reply")
async def reply_to_thread(job_id: str, thread_id: str, body: ReplyRequest):
    """Seller replies to a conversation thread."""
    if not _jobs.get(job_id):
        swarma_line("http", "inbox_reply", job_id=job_id, thread_id=thread_id, error="job_not_found")
        raise HTTPException(status_code=404, detail="Job not found")
    thread = _threads.get(thread_id)
    if not thread:
        swarma_line("http", "inbox_reply", job_id=job_id, thread_id=thread_id, error="thread_not_found")
        raise HTTPException(status_code=404, detail="Thread not found")
    from backend.models.conversation import ChatMessage
    from datetime import datetime
    thread.messages.append(ChatMessage(sender="seller", text=body.text, timestamp=datetime.utcnow()))
    thread.suggested_reply = ""

    await ws_manager.broadcast_event(job_id, {
        "type": "thread_updated",
        "data": thread.model_dump(mode="json"),
    })
    swarma_line("http", "inbox_reply", job_id=job_id, thread_id=thread_id, msg_count=len(thread.messages))
    return thread.model_dump(mode="json")


@app.get("/api/jobs/{job_id}/inbox/{thread_id}/suggest")
async def suggest_reply(job_id: str, thread_id: str):
    """Get an AI-suggested reply for a conversation thread."""
    if not _jobs.get(job_id):
        swarma_line("http", "inbox_suggest", job_id=job_id, thread_id=thread_id, error="job_not_found")
        raise HTTPException(status_code=404, detail="Job not found")
    thread = _threads.get(thread_id)
    if not thread:
        swarma_line("http", "inbox_suggest", job_id=job_id, thread_id=thread_id, error="thread_not_found")
        raise HTTPException(status_code=404, detail="Thread not found")
    # Return cached suggestion if we already have one for this message state
    if thread.suggested_reply:
        return {"thread_id": thread_id, "suggested_reply": thread.suggested_reply}
    try:
        from backend.systems.unified_inbox import UnifiedInboxSystem
        inbox = UnifiedInboxSystem()
        suggestion = await inbox.suggest_reply(thread)
        swarma_line("http", "inbox_suggest", job_id=job_id, thread_id=thread_id, source="ai")
    except Exception as exc:
        logger.exception("Reply suggestion failed for thread %s: %s", thread_id, exc)
        suggestion = _mock_suggest(thread)
        swarma_line("http", "inbox_suggest", job_id=job_id, thread_id=thread_id, source="mock_fallback", error=str(exc))
    # Persist so subsequent /inbox polls include it and frontend skips re-fetching
    thread.suggested_reply = suggestion
    return {"thread_id": thread_id, "suggested_reply": suggestion}


def _mock_suggest(thread: ConversationThread) -> str:
    last = thread.messages[-1] if thread.messages else None
    last_text = (last.text or "").lower() if last else ""

    if thread.current_offer and thread.current_offer > 0:
        return f"Thanks for the offer of ${thread.current_offer:.0f}! I could do ${thread.current_offer * 1.05:.0f} — that's the lowest I can go. Let me know!"

    if any(w in last_text for w in ["condition", "scratches", "damage", "defect"]):
        return "Great question! The item is in the condition described in the listing. I can send more photos if that would help."

    if any(w in last_text for w in ["available", "still have", "sold"]):
        return "Yes, it's still available! Would you like to set up a time to pick it up?"

    if any(w in last_text for w in ["price", "lower", "discount", "deal", "negotiate"]):
        return "I'm open to reasonable offers! What did you have in mind?"

    if any(w in last_text for w in ["ship", "deliver", "mail", "pickup"]):
        return "I can do local pickup or ship it out. Let me know what works best for you!"

    return "Thanks for reaching out! Let me know if you have any questions about the item."


@app.get("/api/buyer-chat/items")
async def buyer_chat_list_items():
    """Return all items across all jobs so the phone buyer-chat can pick one."""
    result = []
    for job_id, items in _job_items.items():
        job = _jobs.get(job_id)
        for item in items:
            hero = item.hero_frame_paths[0] if item.hero_frame_paths else None
            decision = None
            try:
                from backend.storage.store import store
                decision = store.get_decision(item.item_id)
            except Exception:
                pass
            price = 0.0
            if decision:
                price = getattr(decision, "estimated_best_value", 0) or 0
            result.append({
                "item_id": item.item_id,
                "job_id": job_id,
                "name": item.name_guess,
                "title": item.name_guess,
                "condition": item.condition_label,
                "hero_image": hero,
                "price": price,
            })
    swarma_line("http", "buyer_chat_items", items_n=len(result))
    return result


def _find_job_for_item(item_id: str) -> str:
    """Look up which job owns a given item_id."""
    for jid, items in _job_items.items():
        if any(it.item_id == item_id for it in items):
            return jid
    return ""


@app.get("/api/buyer-chat/{item_id}/thread")
async def buyer_chat_get_thread(item_id: str):
    """Get or create the buyer chat thread for an item."""
    thread_id = f"phone-buyer-{item_id}"
    thread = _threads.get(thread_id)
    created = False
    if not thread:
        thread = ConversationThread(
            thread_id=thread_id,
            item_id=item_id,
            job_id=_find_job_for_item(item_id),
            platform="facebook",
            buyer_handle="Phone Buyer",
        )
        _threads[thread_id] = thread
        created = True
    swarma_line("http", "buyer_chat_thread", item_id=item_id, created=created, msg_count=len(thread.messages))
    return thread.model_dump(mode="json")


@app.post("/api/buyer-chat/{item_id}/send")
async def buyer_chat_send(item_id: str, body: BuyerChatRequest):
    """Buyer sends a message; AI seller auto-replies."""
    import re
    from backend.models.conversation import ChatMessage
    from datetime import datetime

    thread_id = f"phone-buyer-{item_id}"
    thread = _threads.get(thread_id)
    if not thread:
        thread = ConversationThread(
            thread_id=thread_id,
            item_id=item_id,
            job_id=_find_job_for_item(item_id),
            platform="facebook",
            buyer_handle=body.buyer_name,
        )
        _threads[thread_id] = thread

    offer_match = re.search(r'\$(\d+(?:\.\d{2})?)', body.text)
    is_offer = offer_match is not None
    offer_amount = float(offer_match.group(1)) if offer_match else None

    thread.messages.append(ChatMessage(
        sender="buyer", text=body.text, timestamp=datetime.utcnow(),
        is_offer=is_offer, offer_amount=offer_amount,
    ))
    if is_offer and offer_amount is not None:
        thread.current_offer = offer_amount

    swarma_line("http", "buyer_chat_send", item_id=item_id, is_offer=is_offer, offer=offer_amount)

    seller_reply = _mock_suggest(thread)
    try:
        from backend.systems.unified_inbox import UnifiedInboxSystem
        inbox = UnifiedInboxSystem()
        seller_reply = await inbox.suggest_reply(thread)
        swarma_line("http", "buyer_chat_auto_reply", item_id=item_id, source="ai")
    except Exception as exc:
        logger.warning("Auto-reply generation failed for %s: %s", thread_id, exc)
        swarma_line("http", "buyer_chat_auto_reply", item_id=item_id, source="mock_fallback", error=str(exc))

    thread.messages.append(ChatMessage(sender="seller", text=seller_reply, timestamp=datetime.utcnow()))
    thread.suggested_reply = ""

    # Broadcast to seller's concierge page via WebSocket
    job_id = thread.job_id or _find_job_for_item(item_id)
    if job_id:
        await ws_manager.broadcast_event(job_id, {
            "type": "thread_updated",
            "data": thread.model_dump(mode="json"),
        })

    return thread.model_dump(mode="json")


@app.get("/api/jobs/{job_id}/items/{item_id}/screenshots")
async def get_item_screenshots(job_id: str, item_id: str):
    """Get the latest screenshot for each listing agent associated with an item.

    Returns {platform: base64_jpeg_or_null} by scanning agent IDs matching
    the pattern "{platform}-listing-{item_id_prefix}".
    """
    if not _jobs.get(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    import base64
    platforms = ["facebook", "depop", "amazon"]
    result = {}
    item_prefix = item_id[:6]
    for platform in platforms:
        agent_id = f"{platform}-listing-{item_prefix}"
        jpeg_bytes = get_frame_for_delivery(agent_id)
        if jpeg_bytes:
            result[platform] = f"data:image/jpeg;base64,{base64.b64encode(jpeg_bytes).decode()}"
        else:
            result[platform] = None
    return result


# ── Concierge Polling Endpoints ───────────────────────────────────────────────


@app.post("/api/jobs/{job_id}/start-concierge")
async def start_concierge(job_id: str):
    """Start FB Marketplace inbox polling agents for all items in this job.

    Called when the Concierge page mounts. Launches one browser agent per item
    that polls the FB Marketplace selling inbox every ~3s for new buyer messages,
    auto-generates replies via Gemini, and types them back into FB Messenger.
    Agents auto-stop after 90 seconds.
    """
    job = _jobs.get(job_id)
    if not job:
        swarma_line("http", "start_concierge", job_id=job_id, error="job_not_found")
        raise HTTPException(status_code=404, detail="Job not found")

    poller = _get_fb_poller()
    if poller is None:
        swarma_line("http", "start_concierge", job_id=job_id, error="poller_unavailable")
        raise HTTPException(status_code=503, detail="FB poller not available")

    if poller.is_running():
        swarma_line("http", "start_concierge", job_id=job_id, status="already_running")
        return {"status": "already_running", "remaining_s": poller._time_remaining()}

    items = _job_items.get(job_id, [])
    if not items:
        swarma_line("http", "start_concierge", job_id=job_id, error="no_items")
        raise HTTPException(status_code=400, detail="No items in this job")

    item_dicts = []
    for item in items:
        price = 0.0
        try:
            from backend.storage.store import store
            decision = store.get_decision(item.item_id)
            if decision:
                price = getattr(decision, "estimated_best_value", 0) or 0
        except Exception:
            pass
        if not price and hasattr(item, "listing_package") and item.listing_package:
            price = item.listing_package.price_strategy or 0
        item_dicts.append({
            "item_id": item.item_id,
            "name": item.name_guess,
            "price": price,
        })

    # Launch polling in background
    asyncio.create_task(_run_concierge(poller, job_id, item_dicts))
    swarma_line("http", "start_concierge", job_id=job_id, items_n=len(item_dicts))
    return {"status": "started", "items": len(item_dicts), "remaining_s": 90}


async def _run_concierge(poller, job_id: str, items: list[dict]):
    """Background task: run poller, auto-stop after 90s."""
    try:
        await poller.start(job_id, items)
        # Wait until stopped or timeout
        while poller.is_running() and poller._time_remaining() > 0:
            await asyncio.sleep(1)
        await poller.stop()
        swarma_line("concierge", "auto_stopped", job_id=job_id)
    except Exception as exc:
        swarma_line("concierge", "error", job_id=job_id, error=str(exc))
        try:
            await poller.stop()
        except Exception:
            pass


@app.post("/api/jobs/{job_id}/stop-concierge")
async def stop_concierge(job_id: str):
    """Stop FB Marketplace inbox polling agents.

    Called when the Concierge page unmounts or user navigates away.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    poller = _get_fb_poller()
    if poller and poller.is_running():
        asyncio.create_task(poller.stop())
        swarma_line("http", "stop_concierge", job_id=job_id, status="stopping")
        return {"status": "stopping"}

    swarma_line("http", "stop_concierge", job_id=job_id, status="not_running")
    return {"status": "not_running"}


@app.get("/api/jobs/{job_id}/concierge-status")
async def concierge_status(job_id: str):
    """Check if concierge polling is active and how much time is left."""
    poller = _get_fb_poller()
    if poller and poller.is_running():
        return {
            "running": True,
            "remaining_s": round(poller._time_remaining(), 1),
            "agents": len(poller._tasks),
        }
    return {"running": False, "remaining_s": 0, "agents": 0}


# ── WebSocket Endpoints ───────────────────────────────────────────────────────


@app.websocket("/ws/{job_id}/events")
async def ws_events(ws: WebSocket, job_id: str):
    """JSON text frames: agent lifecycle events."""
    await ws_manager.connect_events(job_id, ws)
    swarma_line("ws.events", "session_start", job_id=job_id)
    try:
        # Send initial state on connect (reconnection strategy option C)
        job = _jobs.get(job_id)
        if job:
            items = _job_items.get(job_id, [])
            swarma_line(
                "ws.events",
                "initial_state_sending",
                job_id=job_id,
                items_n=len(items),
                job_status=str(job.status.value if hasattr(job.status, "value") else job.status),
            )
            await ws.send_json({
                "type": "initial_state",
                "data": {
                    "job": job.model_dump(mode="json"),
                    "items": [item.model_dump(mode="json") for item in items],
                    "agents": orchestrator.get_agent_states(job_id),
                },
            })
            swarma_line("ws.events", "initial_state_sent", job_id=job_id)
        else:
            swarma_line("ws.events", "initial_state_skipped_no_job", job_id=job_id)

        # Keep connection alive; client messages are currently informational only
        ping_n = 0
        while True:
            raw = await ws.receive_json()
            ping_n += 1
            if ping_n <= 3 or ping_n % 50 == 0:
                swarma_line(
                    "ws.events",
                    "client_ping",
                    job_id=job_id,
                    n=ping_n,
                    payload_keys=sorted(raw.keys()) if isinstance(raw, dict) else type(raw).__name__,
                )

    except WebSocketDisconnect:
        swarma_line("ws.events", "session_disconnect", job_id=job_id)
        ws_manager.disconnect_events(job_id, ws)
    except Exception as exc:
        logger.warning("Events WS error for job %s: %s", job_id, exc)
        swarma_line("ws.events", "session_error", job_id=job_id, error=str(exc))
        ws_manager.disconnect_events(job_id, ws)


@app.websocket("/ws/{job_id}/screenshots")
async def ws_screenshots(ws: WebSocket, job_id: str):
    """Binary frames: CDP screenshots.

    This endpoint is receive-only from the server's perspective.
    The screenshot_push_loop handles sending frames.
    Client just needs to stay connected.
    """
    await ws_manager.connect_screenshots(job_id, ws)
    try:
        # Keep connection alive by reading (client doesn't send much)
        while True:
            await ws.receive_bytes()
    except WebSocketDisconnect:
        ws_manager.disconnect_screenshots(job_id, ws)
    except Exception as exc:
        logger.warning("Screenshots WS error for job %s: %s", job_id, exc)
        ws_manager.disconnect_screenshots(job_id, ws)
