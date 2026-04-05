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

logger = logging.getLogger("reroute.server")

# In-memory thread store for conversation endpoints.
# Mirrors the store.py pattern but scoped to the v2 server.
_threads: dict[str, ConversationThread] = {}


# ── Orchestrator Stub ─────────────────────────────────────────────────────────
# Person 1 (Aditya) builds the real orchestrator. This stub provides the
# interface contract so server.py can be developed and tested independently.


class _OrchestratorStub:
    """Stub matching the confirmed interface from streaming-server-intake-review.md.

    Real interface (from Person 1):
      orchestrator.events           — asyncio.Queue[AgentEvent]
      orchestrator.start_pipeline(job_id, items) — Direct method call

    CDP screencast hook points Person 1 must call when spinning up each agent:
      # When the agent's Playwright Page is ready:
      await streaming.start_screencast(agent_id, page)

      # When the agent completes or is cancelled:
      await streaming.stop_screencast(agent_id)
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
    """Push latest screenshots to all WS clients at a uniform rate.

    All agents are delivered at settings.screenshot_grid_delivery_fps (default 1 fps).
    No per-agent differentiation — the whole swarm is always live simultaneously.

    Uses frame_store (module-level dict in streaming.py) as the source.
    """
    interval = 1.0 / settings.screenshot_grid_delivery_fps
    last_sent: dict[str, float] = {}

    logger.info("Screenshot push loop started for job %s", job_id)
    try:
        while True:
            if not ws_manager.has_screenshot_clients(job_id):
                await asyncio.sleep(0.5)
                continue

            now = time.time()
            for agent_id in get_all_agent_ids():
                if now - last_sent.get(agent_id, 0) < interval:
                    continue

                jpeg_bytes = get_frame_for_delivery(agent_id)
                if jpeg_bytes is None:
                    continue

                binary_frame = encode_binary_frame(agent_id, jpeg_bytes)
                await ws_manager.broadcast_screenshot(job_id, binary_frame)
                last_sent[agent_id] = now

            await asyncio.sleep(interval)

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

        items, _timings, _best_frames = await streaming_analysis(video_path, job_id)

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


app = FastAPI(title="SwarmSell", lifespan=lifespan)

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
    """Accept video upload, start the pipeline in the background.

    Deduplicates by content hash: if the same video was already uploaded,
    reuses the existing file instead of writing another copy.
    """
    job_id = uuid.uuid4().hex[:12]
    job = Job(job_id=job_id, status=JobStatus.UPLOADING)

    # Read upload into memory and compute content hash
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(video.filename or "video.mp4").suffix or ".mp4"

    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    while chunk := await video.read(1024 * 1024):
        hasher.update(chunk)
        chunks.append(chunk)
    content_hash = hasher.hexdigest()[:16]

    # Check for existing file with same hash
    hash_path = upload_dir / f"{content_hash}{ext}"
    if hash_path.exists():
        video_path = hash_path
        logger.info("Upload dedup: reusing %s for job %s", hash_path, job_id)
    else:
        video_path = hash_path
        async with aiofiles.open(video_path, "wb") as f:
            for chunk in chunks:
                await f.write(chunk)
        logger.info("Upload saved: %s (%d bytes) for job %s", video_path, sum(len(c) for c in chunks), job_id)

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


@app.get("/api/jobs/{job_id}/items")
async def get_job_items(job_id: str):
    """Get full ItemCard details for a job."""
    items = _job_items.get(job_id)
    if items is None:
        raise HTTPException(status_code=404, detail="Job not found or no items yet")
    return [item.model_dump() for item in items]


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
        raise HTTPException(status_code=404, detail="Job not found")
    all_threads = []
    for item_id in (job.item_ids or []):
        all_threads.extend(_get_threads_for_item(item_id))
    seriousness_order = {"high": 0, "medium": 1, "low": 2, "spam": 3}
    all_threads.sort(key=lambda t: seriousness_order.get(t.seriousness_score.value if hasattr(t.seriousness_score, 'value') else t.seriousness_score, 99))
    return [t.model_dump(mode="json") for t in all_threads]


@app.post("/api/jobs/{job_id}/inbox/{thread_id}/reply")
async def reply_to_thread(job_id: str, thread_id: str, body: ReplyRequest):
    """Seller replies to a conversation thread."""
    if not _jobs.get(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    thread = _threads.get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    from backend.models.conversation import ChatMessage
    from datetime import datetime
    thread.messages.append(ChatMessage(sender="seller", text=body.text, timestamp=datetime.utcnow()))
    return thread.model_dump(mode="json")


@app.get("/api/jobs/{job_id}/inbox/{thread_id}/suggest")
async def suggest_reply(job_id: str, thread_id: str):
    """Get an AI-suggested reply for a conversation thread."""
    if not _jobs.get(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    thread = _threads.get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    try:
        from backend.systems.unified_inbox import UnifiedInboxSystem
        inbox = UnifiedInboxSystem()
        suggestion = await inbox.suggest_reply(thread)
    except Exception as exc:
        logger.exception("Reply suggestion failed for thread %s: %s", thread_id, exc)
        suggestion = _mock_suggest(thread)
    return {"thread_id": thread_id, "suggested_reply": suggestion}


def _mock_suggest(thread: ConversationThread) -> str:
    if thread.current_offer:
        return f"Thanks for the offer of ${thread.current_offer:.2f}! Let me think about it and get back to you shortly."
    return "Thanks for reaching out! Let me know if you have any questions about the item."


@app.get("/api/buyer-chat/{item_id}/thread")
async def buyer_chat_get_thread(item_id: str):
    """Get or create the buyer chat thread for an item."""
    thread_id = f"phone-buyer-{item_id}"
    thread = _threads.get(thread_id)
    if not thread:
        thread = ConversationThread(
            thread_id=thread_id,
            item_id=item_id,
            platform="facebook",
            buyer_handle="Phone Buyer",
        )
        _threads[thread_id] = thread
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

    seller_reply = _mock_suggest(thread)
    try:
        from backend.systems.unified_inbox import UnifiedInboxSystem
        inbox = UnifiedInboxSystem()
        seller_reply = await inbox.suggest_reply(thread)
    except Exception as exc:
        logger.warning("Auto-reply generation failed for %s: %s", thread_id, exc)

    thread.messages.append(ChatMessage(sender="seller", text=seller_reply, timestamp=datetime.utcnow()))
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
    platforms = ["ebay", "facebook", "mercari", "depop"]
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


# ── WebSocket Endpoints ───────────────────────────────────────────────────────


@app.websocket("/ws/{job_id}/events")
async def ws_events(ws: WebSocket, job_id: str):
    """JSON text frames: agent lifecycle events."""
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

        # Keep connection alive; client messages are currently informational only
        while True:
            await ws.receive_json()

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
