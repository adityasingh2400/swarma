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
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiofiles
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import settings
from backend.models.item_card import ItemCard
from backend.models.job import Job, JobStatus
from backend.streaming import (
    encode_binary_frame,
    focused_agent_id,
    frame_store,
    get_all_agent_ids,
    get_frame_for_delivery,
)
import backend.streaming as streaming_mod

logger = logging.getLogger("reroute.server")


# ── Orchestrator Stub ─────────────────────────────────────────────────────────
# Person 1 (Aditya) builds the real orchestrator. This stub provides the
# interface contract so server.py can be developed and tested independently.


class _OrchestratorStub:
    """Stub matching the confirmed interface from streaming-server-intake-review.md.

    Real interface (from Person 1):
      orchestrator.events           — asyncio.Queue[AgentEvent]
      orchestrator.get_browser(id)  — Returns Browser-Use Browser instance
      orchestrator.start_pipeline(job_id, items) — Direct method call
    """

    def __init__(self):
        self.events: asyncio.Queue = asyncio.Queue()
        self._agents: dict[str, dict] = {}

    async def start_pipeline(self, job_id: str, items: list[ItemCard]) -> None:
        """Stub: emit spawn events for each item's research agents."""
        platforms = ["ebay", "facebook", "mercari", "apple", "amazon"]
        for item in items:
            for platform in platforms:
                agent_id = f"{platform}-research-{item.item_id[:6]}"
                agent_state = {
                    "agent_id": agent_id,
                    "item_id": item.item_id,
                    "platform": platform,
                    "phase": "research",
                    "status": "queued",
                    "task": f"Research {item.name_guess} on {platform}",
                    "started_at": None,
                    "completed_at": None,
                    "result": None,
                    "error": None,
                }
                self._agents[agent_id] = agent_state
                await self.events.put({
                    "type": "agent:spawn",
                    "data": {
                        "agentId": agent_id,
                        "platform": platform,
                        "phase": "research",
                        "task": agent_state["task"],
                    },
                })
        logger.info("Stub orchestrator: queued %d agents for %d items", len(self._agents), len(items))

    def get_browser(self, agent_id: str):
        """Stub: returns None. Real impl returns Browser-Use Browser instance."""
        return None

    def get_agent_states(self, job_id: str) -> dict[str, dict]:
        """Return all agent states. Used by GET /api/jobs/{jobId}/agents."""
        return dict(self._agents)


orchestrator = _OrchestratorStub()


# ── In-Memory Job Store ───────────────────────────────────────────────────────
# Simple dict for hackathon. No persistence needed.

_jobs: dict[str, Job] = {}
_job_items: dict[str, list[ItemCard]] = {}


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
        logger.info("Events WS connected for job %s (%d clients)", job_id, len(self._events[job_id]))

    async def connect_screenshots(self, job_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._screenshots.setdefault(job_id, set()).add(ws)
        logger.info("Screenshots WS connected for job %s (%d clients)", job_id, len(self._screenshots[job_id]))

    def disconnect_events(self, job_id: str, ws: WebSocket) -> None:
        if job_id in self._events:
            self._events[job_id].discard(ws)
            if not self._events[job_id]:
                del self._events[job_id]

    def disconnect_screenshots(self, job_id: str, ws: WebSocket) -> None:
        if job_id in self._screenshots:
            self._screenshots[job_id].discard(ws)
            if not self._screenshots[job_id]:
                del self._screenshots[job_id]

    async def broadcast_event(self, job_id: str, event: dict) -> None:
        """Send a JSON event to all event WS clients for a job."""
        connections = self._events.get(job_id)
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
    """
    logger.info("Event drain loop started for job %s", job_id)
    try:
        while True:
            event = await orchestrator.events.get()
            await ws_manager.broadcast_event(job_id, event)
    except asyncio.CancelledError:
        logger.info("Event drain loop stopped for job %s", job_id)
        raise


async def _screenshot_push_loop(job_id: str):
    """Push latest screenshots to WS clients at configured delivery rates.

    Grid agents: settings.screenshot_grid_delivery_fps (default 1 fps)
    Focused agent: settings.screenshot_focus_delivery_fps (default 3 fps)

    Uses frame_store (module-level dict in streaming.py) as the source.
    """
    grid_interval = 1.0 / settings.screenshot_grid_delivery_fps
    focus_interval = 1.0 / settings.screenshot_focus_delivery_fps
    min_interval = min(grid_interval, focus_interval)

    # Track last delivery time per agent to implement per-agent throttling
    last_sent: dict[str, float] = {}

    logger.info("Screenshot push loop started for job %s", job_id)
    try:
        while True:
            if not ws_manager.has_screenshot_clients(job_id):
                await asyncio.sleep(0.5)
                continue

            now = time.time()
            for agent_id in get_all_agent_ids():
                # Determine delivery interval based on focus state
                is_focused = agent_id == streaming_mod.focused_agent_id
                interval = focus_interval if is_focused else grid_interval

                # Throttle: skip if we sent too recently
                last = last_sent.get(agent_id, 0)
                if now - last < interval:
                    continue

                result = get_frame_for_delivery(agent_id)
                if result is None:
                    continue

                jpeg_bytes, _ = result
                binary_frame = encode_binary_frame(agent_id, jpeg_bytes)
                await ws_manager.broadcast_screenshot(job_id, binary_frame)
                last_sent[agent_id] = now

            await asyncio.sleep(min_interval)

    except asyncio.CancelledError:
        logger.info("Screenshot push loop stopped for job %s", job_id)
        raise


async def _run_pipeline(job_id: str, video_path: str):
    """Main pipeline coroutine: intake → orchestrator → streaming.

    Wrapped in try/except per eng review decision:
    on unhandled error, log, set job FAILED, emit error event, don't re-raise.
    """
    from backend.intake import streaming_analysis

    job = _jobs.get(job_id)
    if not job:
        return

    # Start background loops
    event_drain = asyncio.create_task(_event_drain_loop(job_id))
    screenshot_push = asyncio.create_task(_screenshot_push_loop(job_id))

    try:
        # Phase 1: Intake — video → items
        job.status = JobStatus.ANALYZING
        job.touch()
        await ws_manager.broadcast_event(job_id, {
            "type": "job:progress",
            "data": {"stage": "analyzing", "detail": "Extracting frames and identifying items..."},
        })

        items = await streaming_analysis(video_path, job_id)

        if not items:
            job.status = JobStatus.FAILED
            job.error = "No items detected in video"
            job.touch()
            await ws_manager.broadcast_event(job_id, {
                "type": "agent:error",
                "data": {"agentId": "intake", "error": "No items detected in video"},
            })
            return

        _job_items[job_id] = items
        job.item_ids = [item.item_id for item in items]
        job.touch()

        # Emit item:identified events
        for item in items:
            await ws_manager.broadcast_event(job_id, {
                "type": "item:identified",
                "data": {
                    "itemId": item.item_id,
                    "name": item.name_guess,
                    "confidence": item.confidence,
                },
            })

        # Phase 2: Orchestrator — spawn agents
        job.status = JobStatus.EXECUTING
        job.touch()
        await ws_manager.broadcast_event(job_id, {
            "type": "job:progress",
            "data": {"stage": "executing", "detail": f"Spawning agents for {len(items)} item(s)..."},
        })

        await orchestrator.start_pipeline(job_id, items)

        # Pipeline continues via event_drain_loop and screenshot_push_loop
        # until orchestrator signals completion. For now, we wait.
        # In the real implementation, orchestrator.start_pipeline is blocking
        # until all agents complete.

        job.status = JobStatus.COMPLETED
        job.touch()

    except Exception as exc:
        # Top-level pipeline guard (eng review decision: catch, log, FAIL, emit, don't re-raise)
        logger.exception("Pipeline failed for job %s: %s", job_id, exc)
        job.status = JobStatus.FAILED
        job.error = str(exc)
        job.touch()
        await ws_manager.broadcast_event(job_id, {
            "type": "agent:error",
            "data": {"agentId": "pipeline", "error": f"Pipeline failed: {exc}"},
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


# ── App Lifecycle ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    # Future: warm browser context pool here
    logger.info("ReRoute v2 server starting")
    yield
    logger.info("ReRoute v2 server shutting down")


app = FastAPI(title="ReRoute v2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Endpoints ────────────────────────────────────────────────────────────


class UploadResponse(BaseModel):
    job_id: str
    status: str


@app.post("/api/upload", response_model=UploadResponse)
async def upload_video(video: UploadFile = File(...)):
    """Accept video upload, start the pipeline in the background."""
    job_id = uuid.uuid4().hex[:12]
    job = Job(job_id=job_id, status=JobStatus.UPLOADING)

    # Save uploaded file
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(video.filename or "video.mp4").suffix or ".mp4"
    video_path = upload_dir / f"{job_id}{ext}"

    async with aiofiles.open(video_path, "wb") as f:
        while chunk := await video.read(1024 * 1024):
            await f.write(chunk)

    job.video_path = str(video_path)
    job.status = JobStatus.EXTRACTING
    job.touch()
    _jobs[job_id] = job

    # Start pipeline in background
    asyncio.create_task(_run_pipeline(job_id, str(video_path)))

    return UploadResponse(job_id=job_id, status="processing")


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job status and metadata."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump()


@app.get("/api/jobs/{job_id}/agents")
async def get_agents(job_id: str):
    """Get all agent states for a job. Used for WS reconnection state rebuild."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"agents": orchestrator.get_agent_states(job_id)}


# ── WebSocket Endpoints ───────────────────────────────────────────────────────


@app.websocket("/ws/{job_id}/events")
async def ws_events(ws: WebSocket, job_id: str):
    """JSON text frames: agent lifecycle events.

    Client can send focus:request / focus:release messages to control
    screenshot delivery rate for a specific agent.
    """
    await ws_manager.connect_events(job_id, ws)
    try:
        # Send initial state on connect (reconnection strategy option C)
        job = _jobs.get(job_id)
        if job:
            await ws.send_json({
                "type": "initial_state",
                "data": {
                    "job": job.model_dump(),
                    "agents": orchestrator.get_agent_states(job_id),
                },
            })

        # Listen for client messages (focus mode control)
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "focus:request":
                agent_id = data.get("agent_id")
                if agent_id:
                    streaming_mod.focused_agent_id = agent_id
                    logger.info("Focus mode: %s", agent_id)

            elif msg_type == "focus:release":
                agent_id = data.get("agent_id")
                if streaming_mod.focused_agent_id == agent_id:
                    streaming_mod.focused_agent_id = None
                    logger.info("Focus released: %s", agent_id)

    except WebSocketDisconnect:
        ws_manager.disconnect_events(job_id, ws)
    except Exception as exc:
        logger.warning("Events WS error for job %s: %s", job_id, exc)
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
