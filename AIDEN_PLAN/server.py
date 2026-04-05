from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles

from backend.config import settings
from backend.models import (
    BestRouteDecision,
    ChatMessage,
    ItemCard,
    Job,
    JobStatus,
    ListingPackage,
    RouteBid,
    RouteType,
)
from backend.models.listing_package import PlatformStatus
from backend.storage.store import store
from backend.systems.unified_inbox import UnifiedInboxSystem
from backend.systems.route_closer import RouteCloserSystem

logger = logging.getLogger("reroute.server")


# ── Demo Fallback Guardrails ─────────────────────────────────────────────────
# Known-good value ranges for the demo video items. When the AI-computed value
# falls outside these bands, we clamp to keep the demo visually consistent.
# Keys are matched fuzzily against the Gemini-detected item name.

_DEMO_FALLBACKS: dict[str, dict] = {
    "water bottle": {
        "marketplace_min": 8.0,
        "marketplace_max": 25.0,
        "marketplace_fallback": 15.0,
        "return_min": 15.0,
        "return_max": 35.0,
        "return_fallback": 25.0,
        "trade_in_min": None,
        "trade_in_max": None,
        "trade_in_fallback": None,
    },
    "ipad": {
        "marketplace_min": 120.0,
        "marketplace_max": 400.0,
        "marketplace_fallback": 245.0,
        "return_min": 200.0,
        "return_max": 450.0,
        "return_fallback": 329.0,
        "trade_in_min": 80.0,
        "trade_in_max": 280.0,
        "trade_in_fallback": 175.0,
    },
    "iphone": {
        "marketplace_min": 350.0,
        "marketplace_max": 950.0,
        "marketplace_fallback": 680.0,
        "return_min": 500.0,
        "return_max": 1100.0,
        "return_fallback": 799.0,
        "trade_in_min": 250.0,
        "trade_in_max": 650.0,
        "trade_in_fallback": 420.0,
    },
}


def _match_fallback(item_name: str) -> dict | None:
    """Fuzzy-match an item name against the demo fallback table."""
    name_lower = item_name.lower()
    for key, fb in _DEMO_FALLBACKS.items():
        if key in name_lower:
            return fb
    return None


def _clamp_value(
    value: float, item_name: str, route_type: str,
) -> float:
    """Clamp a computed value to the demo-safe range. Returns the original value
    if no fallback matches or if the value is already within range."""
    fb = _match_fallback(item_name)
    if fb is None:
        return value

    key_min = f"{route_type}_min"
    key_max = f"{route_type}_max"
    key_fallback = f"{route_type}_fallback"

    lo = fb.get(key_min)
    hi = fb.get(key_max)
    fallback = fb.get(key_fallback)

    if lo is None or hi is None or fallback is None:
        return value

    if value <= 0:
        print(f"[FALLBACK] {item_name} {route_type}: ${value:.0f} → ${fallback:.0f} (was zero/negative)")
        return fallback
    if value < lo or value > hi:
        clamped = max(lo, min(hi, value))
        print(f"[FALLBACK] {item_name} {route_type}: ${value:.0f} → ${clamped:.0f} (outside ${lo:.0f}–${hi:.0f})")
        return clamped
    return value


# ── WebSocket Connection Manager ─────────────────────────────────────────────


class ConnectionManager:
    def __init__(self) -> None:
        self._active: dict[str, set[WebSocket]] = {}
        self._event_count: int = 0

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active.setdefault(job_id, set()).add(websocket)
        print(f"[WS] Client connected for job {job_id} ({len(self._active[job_id])} clients)")

    def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        if job_id in self._active:
            self._active[job_id].discard(websocket)
            if not self._active[job_id]:
                del self._active[job_id]

    async def broadcast(self, job_id: str, event_type: str, data: dict) -> None:
        connections = self._active.get(job_id)
        if not connections:
            return
        self._event_count += 1
        payload = {"type": event_type, "data": data}
        stale: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            connections.discard(ws)


manager = ConnectionManager()


async def _store_event_handler(event_type: str, data: dict) -> None:
    job_id = data.get("job_id")
    if not job_id:
        item_id = data.get("item_id")
        if item_id:
            item = store.get_item(item_id)
            if item:
                job_id = item.job_id
    if job_id:
        await manager.broadcast(job_id, event_type, data)


# ── App Lifecycle ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    store.on_event(_store_event_handler)

    from backend.services.gemini import GeminiService, load_demo_snapshot

    svc = GeminiService()

    async def _full_warmup():
        import time as _t
        t0 = _t.time()

        if load_demo_snapshot():
            elapsed = _t.time() - t0
            print(f"[READY] Loaded in {elapsed:.2f}s")
        else:
            print(f"[WARMUP] Preparing pipeline...")
            try:
                await svc.precompute_demo_pipeline()
            except Exception as exc:
                print(f"\n  [Warmup] ⚠ Warmup failed: {exc}")
                import traceback
                traceback.print_exc()

        print(r"""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║     ██████╗ ███████╗ █████╗ ██████╗ ██╗   ██╗                ║
    ║     ██╔══██╗██╔════╝██╔══██╗██╔══██╗╚██╗ ██╔╝                ║
    ║     ██████╔╝█████╗  ███████║██║  ██║ ╚████╔╝                 ║
    ║     ██╔══██╗██╔══╝  ██╔══██║██║  ██║  ╚██╔╝                  ║
    ║     ██║  ██║███████╗██║  ██║██████╔╝   ██║                   ║
    ║     ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝    ╚═╝                   ║
    ║                                                               ║
    ║     Ready to demo!                                            ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
""", flush=True)

    asyncio.create_task(_full_warmup())

    yield


app = FastAPI(title="ReRoute", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Schemas ────────────────────────────────────────────────


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "reroute"}


@app.get("/api/local-ip")
async def get_local_ip() -> dict[str, str]:
    import socket
    ip = "localhost"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    return {"ip": ip}


class UploadResponse(BaseModel):
    job_id: str
    status: str


class ExecuteRequest(BaseModel):
    platforms: list[str]


class ReplyRequest(BaseModel):
    text: str


class CloseRouteRequest(BaseModel):
    winning_platform: str
    recovered_value: float


# ── Upload ────────────────────────────────────────────────────────────────────


@app.post("/api/upload", response_model=UploadResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix or ".mp4"
    dest = Path(settings.upload_dir) / f"{uuid.uuid4().hex[:12]}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            await out.write(chunk)

    job = await store.create_job(video_path=str(dest))
    background_tasks.add_task(run_pipeline, job.job_id)
    return UploadResponse(job_id=job.job_id, status=job.status.value)


# ── Jobs ──────────────────────────────────────────────────────────────────────


@app.get("/api/jobs")
async def list_jobs() -> list[dict[str, Any]]:
    return [j.model_dump(mode="json") for j in store.list_jobs()]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    state = store.get_full_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    return state


@app.get("/api/jobs/{job_id}/items")
async def get_items(job_id: str) -> list[dict[str, Any]]:
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return [i.model_dump(mode="json") for i in store.get_items_for_job(job_id)]


@app.get("/api/jobs/{job_id}/items/{item_id}/bids")
async def get_bids(job_id: str, item_id: str) -> list[dict[str, Any]]:
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return [b.model_dump(mode="json") for b in store.get_bids(item_id)]


@app.get("/api/jobs/{job_id}/items/{item_id}/decision")
async def get_decision(job_id: str, item_id: str) -> dict[str, Any]:
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    decision = store.get_decision(item_id)
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision.model_dump(mode="json")


# ── Execution ─────────────────────────────────────────────────────────────────


@app.post("/api/jobs/{job_id}/items/{item_id}/execute")
async def execute_item(
    job_id: str,
    item_id: str,
    body: ExecuteRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if not store.get_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    background_tasks.add_task(run_execution, job_id, item_id, body.platforms)
    return {"status": "executing", "item_id": item_id, "platforms": body.platforms}


@app.post("/api/jobs/{job_id}/items/{item_id}/close")
async def close_route(
    job_id: str, item_id: str, body: CloseRouteRequest
) -> dict[str, Any]:
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if not store.get_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    closer = RouteCloserSystem()
    await closer.close_losing_routes(item_id, body.winning_platform)
    await closer.mark_resolved(item_id, body.recovered_value)
    return {
        "status": "closed",
        "item_id": item_id,
        "winning_platform": body.winning_platform,
        "recovered_value": body.recovered_value,
    }


# ── Inbox ─────────────────────────────────────────────────────────────────────


@app.get("/api/jobs/{job_id}/inbox")
async def get_inbox(job_id: str) -> list[dict[str, Any]]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    inbox = UnifiedInboxSystem()
    # Parallelize ranking across items — rank_buyers is async
    results = await asyncio.gather(
        *[inbox.rank_buyers(item_id) for item_id in job.item_ids],
        return_exceptions=True,
    )
    results = [r for r in results if not isinstance(r, Exception)]
    threads: list[dict[str, Any]] = [
        t.model_dump(mode="json") for result in results for t in result
    ]
    return threads


@app.post("/api/jobs/{job_id}/inbox/{thread_id}/reply")
async def reply_to_thread(
    job_id: str, thread_id: str, body: ReplyRequest
) -> dict[str, Any]:
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    thread = store.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    inbox = UnifiedInboxSystem()
    updated = await inbox.add_message(thread_id, sender="seller", text=body.text)
    return updated.model_dump(mode="json")


@app.get("/api/jobs/{job_id}/inbox/{thread_id}/suggest")
async def suggest_reply(job_id: str, thread_id: str) -> dict[str, Any]:
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    thread = store.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    inbox = UnifiedInboxSystem()
    suggestion = await inbox.suggest_reply(thread)
    return {"thread_id": thread_id, "suggested_reply": suggestion}


# ── Buyer Chat (phone) ───────────────────────────────────────────────────────


class BuyerChatRequest(BaseModel):
    text: str
    buyer_name: str = "Buyer"


@app.get("/api/buyer-chat/items")
async def buyer_chat_items() -> list[dict[str, Any]]:
    """Return all items across all jobs so the phone can pick one to chat about."""
    all_items = []
    for job in store.list_jobs():
        for item_id in job.item_ids:
            item = store.get_item(item_id)
            listing = store.get_listing(item_id)
            if item:
                entry = {
                    "item_id": item.item_id,
                    "job_id": job.job_id,
                    "name": item.name_guess,
                    "condition": item.condition_label,
                    "hero_image": item.hero_frame_paths[0] if item.hero_frame_paths else None,
                    "price": listing.price_strategy if listing else None,
                    "title": listing.title if listing else item.name_guess,
                    "description": listing.description if listing else "",
                }
                all_items.append(entry)
    return all_items


@app.get("/api/buyer-chat/{item_id}/thread")
async def buyer_chat_get_thread(item_id: str) -> dict[str, Any]:
    """Get or create the buyer chat thread for an item."""
    thread_id = f"phone-buyer-{item_id}"
    thread = store.get_thread(thread_id)
    if not thread:
        from backend.models.conversation import ConversationThread
        thread = ConversationThread(
            thread_id=thread_id,
            item_id=item_id,
            platform="facebook",
            buyer_handle="Phone Buyer",
        )
        item = store.get_item(item_id)
        if item:
            thread.job_id = item.job_id
        await store.add_thread(thread)
    return thread.model_dump(mode="json")


@app.post("/api/buyer-chat/{item_id}/send")
async def buyer_chat_send(item_id: str, body: BuyerChatRequest) -> dict[str, Any]:
    """Buyer sends a message; AI seller auto-replies."""
    thread_id = f"phone-buyer-{item_id}"
    inbox = UnifiedInboxSystem()

    # Check for price offers in the message
    import re
    offer_match = re.search(r'\$(\d+(?:\.\d{2})?)', body.text)
    is_offer = offer_match is not None
    offer_amount = float(offer_match.group(1)) if offer_match else None

    await inbox.add_message(
        thread_id, sender="buyer", text=body.text,
        is_offer=is_offer, offer_amount=offer_amount,
    )

    thread = store.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Ensure thread has item_id set
    if not thread.item_id:
        thread.item_id = item_id
        item = store.get_item(item_id)
        if item:
            thread.job_id = item.job_id
        thread.platform = "facebook"
        thread.buyer_handle = body.buyer_name
        await store.add_thread(thread)

    seller_reply = await inbox.suggest_reply(thread)

    await inbox.add_message(thread_id, sender="seller", text=seller_reply)

    thread = store.get_thread(thread_id)
    return thread.model_dump(mode="json")


# ── WebSocket ─────────────────────────────────────────────────────────────────


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str) -> None:
    await manager.connect(job_id, websocket)
    try:
        state = store.get_full_state(job_id)
        if state:
            await websocket.send_json({"type": "initial_state", "data": state})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(job_id, websocket)


# ── Agent Lifecycle Events ────────────────────────────────────────────────────


async def emit_agent_event(job_id: str, event_type: str, data: dict) -> None:
    """Broadcast agent lifecycle event AND persist state for reconnection.

    Agent event data flow:
      emit_agent_event() → store.set_agent_state() → manager.broadcast()
                                                        ↓
                                           useJob hook receives event
                                                        ↓
                                        AgentStatusBar + MissionControl re-render
    """
    try:
        store.set_agent_state(job_id, data.get("agent", ""), {"status": event_type, **data})
        await manager.broadcast(job_id, event_type, data)
    except Exception:
        logger.warning("emit_agent_event failed for job=%s agent=%s", job_id, data.get("agent"), exc_info=True)


# ── Pipeline Orchestration ────────────────────────────────────────────────────


async def run_pipeline(job_id: str) -> None:
    import time as _time
    try:
        job = store.get_job(job_id)
        if not job or not job.video_path:
            print(f"[PIPELINE] ERROR: Job {job_id} not found or no video_path")
            return

        print(f"\n[PIPELINE] ═══ Starting pipeline for job {job_id} ═══")
        print(f"[PIPELINE] Video: {job.video_path}")

        # ── Fused Stage: Extract frames + transcript + analysis concurrently ──
        print(f"[PIPELINE] Fused Stage: Extracting frames, transcribing, and analyzing concurrently...")
        t0 = _time.time()
        await store.update_job_status(job_id, JobStatus.ANALYZING)
        await emit_agent_event(job_id, "agent_started", {"agent": "intake", "message": "Processing video — extracting, transcribing, and analyzing concurrently..."})

        from backend.services.media import MediaService
        from backend.services.gemini import GeminiService

        media_svc = MediaService()
        gemini = GeminiService()

        await emit_agent_event(job_id, "agent_progress", {"agent": "intake", "message": "Analyzing video with Gemini...", "progress": 0.1})

        async def _on_frames_done(fps):
            # Staged reveal: frames appear one by one (~4s total)
            from pathlib import Path as _P
            for i, p in enumerate(fps):
                frame_urls = [f"/frames/{_P(fp).name}" for fp in fps[:i + 1]]
                await emit_agent_event(job_id, "agent_progress", {
                    "agent": "intake",
                    "message": f"Extracting frame {i + 1}/{len(fps)}...",
                    "progress": 0.05 + 0.25 * (i + 1) / len(fps),
                    "frame_paths": frame_urls,
                })
                await asyncio.sleep(0.30)

        async def _on_transcript_done(t):
            await asyncio.sleep(0.4)
            await emit_agent_event(job_id, "agent_progress", {
                "agent": "intake",
                "message": f"Transcript: {t[:80]}..." if len(t) > 80 else f"Transcript: {t}",
                "progress": 0.5,
                "transcript_text": t,
            })
            await asyncio.sleep(0.6)

        async def _on_analysis_done(itms):
            await asyncio.sleep(0.3)
            await emit_agent_event(job_id, "agent_progress", {
                "agent": "condition_fusion",
                "message": f"Found {len(itms)} items — grading each one...",
                "progress": 0.7,
            })

        frame_paths, transcript, items = await gemini.extract_and_analyze(
            video_path=job.video_path,
            extract_frames_fn=media_svc.extract_frames,
            on_frames_done=_on_frames_done,
            on_transcript_done=_on_transcript_done,
            on_analysis_done=_on_analysis_done,
        )

        elapsed_fused = round((_time.time() - t0) * 1000)
        await emit_agent_event(job_id, "agent_completed", {
            "agent": "intake",
            "message": f"Extracted {len(frame_paths)} frames, {len(transcript)} chars transcript, {len(items)} items analyzed",
            "elapsed_ms": elapsed_fused,
            "frame_count": len(frame_paths),
            "transcript_length": len(transcript),
        })
        print(f"[PIPELINE] ✓ Fused stage done in {_time.time()-t0:.1f}s — {len(frame_paths)} frames, {len(transcript)} chars, {len(items)} items")

        job = await store.update_job_status(
            job_id,
            JobStatus.ANALYZING,
            transcript_text=transcript,
            frame_paths=frame_paths,
        )

        for idx, item in enumerate(items):
            item.job_id = job_id
            await store.add_item(item)
            await emit_agent_event(job_id, "agent_progress", {
                "agent": "condition_fusion",
                "message": f"Graded: {item.name_guess} — {item.condition_label} ({item.confidence:.0%})",
                "progress": 0.7 + (0.3 * (idx + 1) / max(len(items), 1)),
            })
            print(f"[PIPELINE]   • {item.name_guess} (confidence: {item.confidence:.0%}, defects: {len(item.all_defects)})")
            await asyncio.sleep(1.0)

        await emit_agent_event(job_id, "agent_completed", {
            "agent": "condition_fusion",
            "message": f"Graded {len(items)} items",
            "elapsed_ms": elapsed_fused,
            "item_count": len(items),
        })
        print(f"[PIPELINE] ✓ All {len(items)} items graded")

        # Pause so viewers can scroll and appreciate the item cards before advancing
        await asyncio.sleep(5.0)

        if not items:
            print(f"[PIPELINE] No items detected, completing job")
            await store.update_job_status(job_id, JobStatus.COMPLETED)
            return

        # ── Stage 3: Route bidding — ALL items in parallel, all agents per item in parallel ──
        print(f"\n[STAGE3] ═══════════════════════════════════════════════════════════════")
        print(f"[STAGE3]  ROUTE BIDDING — {len(items)} items × up to 5 agents each")
        print(f"[STAGE3] ═══════════════════════════════════════════════════════════════")
        t2 = _time.time()
        await store.update_job_status(job_id, JobStatus.ROUTING)

        ROUTE_TO_AGENT = {
            "sell_as_is": "marketplace_resale",
            "trade_in": "trade_in",
            "repair_then_sell": "repair_roi",
            "return": "return",
        }

        from backend.services.gemini import GeminiService as _GS
        key_count = _GS.get_key_count()

        # Build the plan: which agents run for which items
        item_agent_plan: dict[str, list[str]] = {}
        total_tasks = 0
        for item in items:
            agents_for = ["marketplace_resale", "return"]
            if item.is_electronics:
                agents_for.append("trade_in")
            if item.has_defects:
                agents_for.append("repair_roi")
            item_agent_plan[item.item_id] = agents_for
            total_tasks += len(agents_for)

        # Log the concurrency plan
        print(f"[STAGE3]")
        print(f"[STAGE3]  CONCURRENCY PLAN:")
        print(f"[STAGE3]  ┌{'─'*64}┐")
        for idx_i, item in enumerate(items):
            agent_list = item_agent_plan[item.item_id]
            name_short = item.name_guess[:30]
            print(f"[STAGE3]  │ Item {idx_i+1}/{len(items)}: {name_short:<30} │ {len(agent_list)} agents │")
            for ag in agent_list:
                api_note = "[Gemini]" if ag == "marketplace_resale" else "[local] "
                print(f"[STAGE3]  │   ├─ {ag:<25} {api_note}        │")
        print(f"[STAGE3]  └{'─'*64}┘")
        print(f"[STAGE3]  Total concurrent tasks: {total_tasks}")
        print(f"[STAGE3]  Gemini API keys available: {key_count} (round-robin)")
        gemini_per_item = 3  # mercari_swappa + facebook_offerup + poshmark_amazon
        gemini_tasks = gemini_per_item * len(items)
        print(f"[STAGE3]  Gemini search calls: {gemini_tasks} concurrent ({gemini_per_item} platform groups × {len(items)} items)")
        print(f"[STAGE3]  Plus {len(items)} direct eBay API calls (no Gemini key needed)")
        if key_count > 0:
            print(f"[STAGE3]  Load per key: ~{gemini_tasks / key_count:.1f} concurrent Gemini calls/key")
        print(f"[STAGE3]")

        # Emit stage3_plan to frontend
        plan_data = {}
        for item in items:
            plan_data[item.item_id] = {
                "name": item.name_guess,
                "agents": item_agent_plan[item.item_id],
                "hero_frame": item.hero_frame_paths[0] if item.hero_frame_paths else None,
                "condition": item.condition_label,
                "confidence": item.confidence,
            }
        await manager.broadcast(job_id, "stage3_plan", {
            "plan": plan_data,
            "total_concurrent_tasks": total_tasks,
            "gemini_keys": key_count,
        })

        # Track timing for the concurrency waterfall
        task_timings: list[dict] = []
        # Collect bids per item for decision phase (thread-safe via asyncio single-thread)
        item_bids: dict[str, list[RouteBid]] = {item.item_id: [] for item in items}

        async def _run_agent_task(
            i: int, item: ItemCard, agent_name: str,
            task_name: str, coro: Any, uses_gemini: bool = False,
        ) -> None:
            """Fully self-contained agent task: emits started, runs, emits completed, stores bid."""
            # Stagger agent starts so they visually cascade
            await asyncio.sleep(i * 0.3 + 0.1)
            item_t = _time.time()

            await emit_agent_event(job_id, "agent_started", {
                "agent": agent_name, "item_id": item.item_id,
                "item_index": i, "total_items": len(items),
                "item_name": item.name_guess,
                "message": f"Evaluating {item.name_guess}...",
            })

            try:
                # Run the actual bid coroutine
                result = await coro
                elapsed = _time.time() - item_t

                if result and result.viable:
                    item_bids[item.item_id].append(result)
                    await store.add_bid(result)
                    await emit_agent_event(job_id, "agent_completed", {
                        "agent": agent_name, "item_id": item.item_id,
                        "item_index": i, "total_items": len(items),
                        "item_name": item.name_guess,
                        "message": f"${result.estimated_value:.0f} — {result.explanation}",
                        "confidence": result.confidence,
                        "estimated_value": result.estimated_value,
                        "elapsed_ms": round(elapsed * 1000),
                    })
                    value_str = f"${result.estimated_value:.0f}"
                    print(f"[STAGE3] [Item {i+1}] [Agent: {agent_name}] ✓ Done in {elapsed:.1f}s → {value_str} (conf: {result.confidence:.0%})")
                else:
                    # Store non-viable bids too so frontend can show why
                    if result:
                        await store.add_bid(result)
                    await emit_agent_event(job_id, "agent_completed", {
                        "agent": agent_name, "item_id": item.item_id,
                        "item_index": i, "total_items": len(items),
                        "item_name": item.name_guess,
                        "message": result.explanation if result else "Not viable for this item",
                        "elapsed_ms": round(elapsed * 1000),
                    })
                    print(f"[STAGE3] [Item {i+1}] [Agent: {agent_name}] ✓ Done in {elapsed:.1f}s → N/A")

                task_timings.append({
                    "item_idx": i, "agent": agent_name, "task": task_name,
                    "start_offset": item_t - t2, "end_offset": _time.time() - t2,
                    "elapsed": elapsed, "key": "Gemini" if uses_gemini else None,
                })

            except Exception as exc:
                elapsed = _time.time() - item_t
                print(f"[STAGE3] [Item {i+1}] [Agent: {agent_name}] ✗ FAILED in {elapsed:.1f}s: {exc}")
                await emit_agent_event(job_id, "agent_error", {
                    "agent": agent_name, "item_id": item.item_id,
                    "item_index": i, "total_items": len(items),
                    "item_name": item.name_guess,
                    "error": f"Failed: {exc}",
                })
                task_timings.append({
                    "item_idx": i, "agent": agent_name, "task": task_name,
                    "start_offset": item_t - t2, "end_offset": _time.time() - t2,
                    "elapsed": elapsed, "key": "Gemini" if uses_gemini else None,
                })

        async def _run_marketplace_with_heartbeat(
            i: int, item: ItemCard,
        ) -> None:
            """Multi-source marketplace search: fires eBay API + parallel Gemini
            platform searches. Streams comparables to frontend as each source returns."""
            item_t = _time.time()
            agent_name = "marketplace_resale"
            all_comps: list = []

            await emit_agent_event(job_id, "agent_started", {
                "agent": agent_name, "item_id": item.item_id,
                "item_index": i, "total_items": len(items),
                "item_name": item.name_guess,
                "message": f"Searching marketplaces for {item.name_guess}...",
            })

            from backend.services.ebay_api import EbayService
            from backend.services.gemini import GeminiService
            from backend.models.route_bid import EffortLevel, SpeedEstimate

            gemini_svc = GeminiService()
            ebay_svc = EbayService()

            async def _search_ebay():
                try:
                    results = await ebay_svc.search_comps(item.name_guess)
                    print(f"[STAGE3] [Item {i+1}] [marketplace] eBay API returned {len(results)} listings in {_time.time()-item_t:.1f}s")
                    return ("ebay", results)
                except Exception as exc:
                    print(f"[STAGE3] [Item {i+1}] [marketplace] eBay API failed: {exc}")
                    return ("ebay", [])

            async def _search_gemini_group(platforms: list[str], group_name: str):
                try:
                    results = await gemini_svc.search_platform(
                        item_name=item.name_guess,
                        platforms=platforms,
                        condition=item.condition_label,
                    )
                    print(f"[STAGE3] [Item {i+1}] [marketplace] {group_name} returned {len(results)} listings in {_time.time()-item_t:.1f}s")
                    return (group_name, results)
                except Exception as exc:
                    print(f"[STAGE3] [Item {i+1}] [marketplace] {group_name} failed: {exc}")
                    return (group_name, [])

            # Fire all sources in parallel
            search_tasks = [
                asyncio.create_task(_search_ebay()),
                asyncio.create_task(_search_gemini_group(["Mercari", "Swappa"], "mercari_swappa")),
                asyncio.create_task(_search_gemini_group(["Facebook Marketplace", "OfferUp"], "facebook_offerup")),
                asyncio.create_task(_search_gemini_group(["Poshmark", "Amazon", "Craigslist"], "poshmark_amazon")),
            ]

            sources_done = 0
            total_sources = len(search_tasks)

            # Process results as each source completes, with paced reveals
            for completed_task in asyncio.as_completed(search_tasks):
                source_name, comps = await completed_task
                sources_done += 1
                elapsed = _time.time() - item_t

                # Minimum 2.5s between source reveals for demo pacing
                source_target = sources_done * 2.5
                if elapsed < source_target:
                    await asyncio.sleep(source_target - elapsed)
                    elapsed = _time.time() - item_t

                if comps:
                    all_comps.extend(comps)
                    # Stream comparables to frontend with per-listing pacing
                    for ci, c in enumerate(comps):
                        await manager.broadcast(job_id, "comps_found", {
                            "item_id": item.item_id,
                            "source": source_name,
                            "comparables": [{
                                "platform": c.platform, "title": c.title,
                                "price": c.price, "shipping": c.shipping,
                                "condition": c.condition, "url": c.url,
                                "image_url": c.image_url, "match_score": c.match_score,
                            }],
                            "total_so_far": len(all_comps) - len(comps) + ci + 1,
                        })
                        if ci < len(comps) - 1:
                            await asyncio.sleep(0.6)

                    platforms_found = list({c.platform for c in comps})
                    await emit_agent_event(job_id, "agent_progress", {
                        "agent": agent_name, "item_id": item.item_id,
                        "item_index": i, "total_items": len(items),
                        "item_name": item.name_guess,
                        "message": f"Found {len(all_comps)} listings — {', '.join(platforms_found)} ({elapsed:.0f}s)",
                        "progress": sources_done / total_sources * 0.9,
                    })
                else:
                    await emit_agent_event(job_id, "agent_progress", {
                        "agent": agent_name, "item_id": item.item_id,
                        "item_index": i, "total_items": len(items),
                        "item_name": item.name_guess,
                        "message": f"Searched {source_name} — {sources_done}/{total_sources} sources done ({elapsed:.0f}s)",
                        "progress": sources_done / total_sources * 0.9,
                    })

            # All sources done — compute final bid
            elapsed = _time.time() - item_t
            if all_comps:
                relevant_comps = [c for c in all_comps if c.match_score >= 60]
                if len(relevant_comps) < 3:
                    relevant_comps = all_comps
                prices = sorted([c.price for c in relevant_comps if c.price > 0])

                if len(prices) >= 4:
                    q1_idx = len(prices) // 4
                    q3_idx = 3 * len(prices) // 4
                    q1, q3 = prices[q1_idx], prices[q3_idx]
                    iqr = q3 - q1
                    lower_fence = q1 - 1.5 * iqr
                    upper_fence = q3 + 1.5 * iqr
                    prices = [p for p in prices if lower_fence <= p <= upper_fence]

                if prices:
                    median_price = prices[len(prices) // 2]
                    avg = sum(prices) / len(prices)
                    fair_value = 0.6 * median_price + 0.4 * avg
                else:
                    fair_value = median_price = 0

                cond_label = item.condition_label
                cond_mult = {"Like New": 0.95, "Good": 0.82, "Fair": 0.60}.get(cond_label, 0.75)
                net = round(fair_value * cond_mult * 0.87, 2)
                net = _clamp_value(net, item.name_guess, "marketplace")
                platforms_found = list({c.platform for c in all_comps})
                print(f"[STAGE3] [Item {i+1}] [pricing] {len(all_comps)} comps → "
                      f"{len(relevant_comps)} relevant (score≥60) → {len(prices)} after outlier filter | "
                      f"median ${median_price:.0f}, avg ${avg:.0f}, fair_value ${fair_value:.0f} "
                      f"× {cond_label} ({cond_mult}) × 0.87 = ${net:.0f}")

                bid = RouteBid(
                    item_id=item.item_id,
                    route_type=RouteType.SELL_AS_IS,
                    estimated_value=net,
                    effort=EffortLevel.MODERATE,
                    speed=SpeedEstimate.WEEK,
                    confidence=min(len(all_comps) / 5, 1.0),
                    comparable_listings=all_comps,
                    explanation=f"Found {len(all_comps)} comps across {', '.join(platforms_found)}: ~${net:.0f} net after fees (median ${median_price:.0f})",
                )
                item_bids[item.item_id].append(bid)
                await store.add_bid(bid)
                await emit_agent_event(job_id, "agent_completed", {
                    "agent": agent_name, "item_id": item.item_id,
                    "item_index": i, "total_items": len(items),
                    "item_name": item.name_guess,
                    "message": f"${net:.0f} — {len(all_comps)} comps from {len(platforms_found)} platforms",
                    "confidence": min(len(all_comps) / 5, 1.0),
                    "estimated_value": net,
                    "elapsed_ms": round(elapsed * 1000),
                })
                print(f"[STAGE3] [Item {i+1}] [marketplace] ✓ ALL DONE in {elapsed:.1f}s — {len(all_comps)} comps, avg ${avg:.0f}, net ${net:.0f}")
            else:
                await emit_agent_event(job_id, "agent_completed", {
                    "agent": agent_name, "item_id": item.item_id,
                    "item_index": i, "total_items": len(items),
                    "item_name": item.name_guess,
                    "message": "No comparable listings found",
                    "elapsed_ms": round(elapsed * 1000),
                })
                print(f"[STAGE3] [Item {i+1}] [marketplace] ✗ No comps found in {elapsed:.1f}s")

            task_timings.append({
                "item_idx": i, "agent": agent_name, "task": "marketplace_multi_source",
                "start_offset": item_t - t2, "end_offset": _time.time() - t2,
                "elapsed": elapsed, "key": "Gemini",
            })

        # Build ALL tasks across ALL items — truly flat concurrent list
        all_tasks: list[Any] = []
        for i, item in enumerate(items):
            bid_agents = item_agent_plan[item.item_id]
            item_short = item.name_guess[:25]
            print(f"[STAGE3] ── Item {i+1}/{len(items)}: \"{item_short}\" — {len(bid_agents)} agents ──")

            # Marketplace resale gets special heartbeat treatment
            all_tasks.append(_run_marketplace_with_heartbeat(i, item))

            # Local agents — each self-contained
            if "trade_in" in bid_agents:
                all_tasks.append(_run_agent_task(i, item, "trade_in", "trade_in_quotes", _bid_trade_in(item)))
            if "repair_roi" in bid_agents:
                all_tasks.append(_run_agent_task(i, item, "repair_roi", "repair_parts", _bid_repair(item)))
            all_tasks.append(_run_agent_task(i, item, "return", "return_eval", _bid_return(item)))

        print(f"[STAGE3] Launching {len(all_tasks)} fully independent agent tasks across {len(items)} items...")
        results = await asyncio.gather(*all_tasks, return_exceptions=True)
        for idx_r, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Agent task %d failed: %s", idx_r, result, exc_info=result)

        # Let viewers absorb the comparative listings before route bidding decisions
        await asyncio.sleep(5.0)

        # Stage 4: Decisions + listing generation for ALL items in parallel
        from backend.systems.listing_asset_optimization import ListingAssetOptimizationSystem
        from backend.models.listing_package import ListingPackage, ListingImage

        async def _decide_and_generate(i: int, item: ItemCard) -> None:
            """Score bids, pick winner, generate listing — fully self-contained per item."""
            # Stagger items so decisions don't all appear at once
            await asyncio.sleep(i * 1.5)

            bids_for = item_bids[item.item_id]
            await emit_agent_event(job_id, "agent_started", {
                "agent": "route_decider", "item_id": item.item_id,
                "item_index": i, "total_items": len(items),
                "item_name": item.name_guess,
                "message": f"Scoring {len(bids_for)} bids for {item.name_guess}...",
            })
            await asyncio.sleep(0.8)
            decision = _decide_best_route(item.item_id, bids_for)
            await store.set_decision(decision)
            await emit_agent_event(job_id, "agent_completed", {
                "agent": "route_decider", "item_id": item.item_id,
                "item_index": i, "total_items": len(items),
                "item_name": item.name_guess,
                "message": f"Best: {decision.best_route.value} → ${decision.estimated_best_value:.2f}",
                "estimated_value": decision.estimated_best_value,
                "elapsed_ms": round((_time.time() - t2) * 1000),
            })
            print(f"[STAGE3] [Item {i+1}] ★ Best route: {decision.best_route.value} → ${decision.estimated_best_value:.2f}")
            await asyncio.sleep(0.5)

            try:
                optimizer = ListingAssetOptimizationSystem()
                optimized_images = await optimizer.optimize(item)
                comp_prices = []
                for bid in bids_for:
                    for comp in bid.comparable_listings:
                        if comp.price > 0:
                            comp_prices.append(comp.price)
                listing_data = await gemini.generate_listing(item, comp_prices=comp_prices or None)
                listing = ListingPackage(
                    item_id=item.item_id, job_id=job_id,
                    title=listing_data.get("title", item.name_guess),
                    description=listing_data.get("description", ""),
                    specs=item.likely_specs,
                    condition_summary=listing_data.get("condition_summary", item.condition_label),
                    defects_disclosure=listing_data.get("defects_disclosure", ""),
                    price_strategy=_clamp_value(listing_data.get("price_strategy", 0.0), item.name_guess, "marketplace"),
                    price_min=_clamp_value(listing_data.get("price_min", 0.0), item.name_guess, "marketplace"),
                    price_max=_clamp_value(listing_data.get("price_max", 0.0), item.name_guess, "marketplace"),
                    images=optimized_images,
                )
                await store.set_listing(listing)
                print(f"[STAGE3] [Item {i+1}] ✓ Listing: {listing.title} ({len(optimized_images)} images)")
            except Exception as exc:
                print(f"[STAGE3] [Item {i+1}] ⚠ Asset optimization skipped: {exc}")

        await asyncio.gather(*[_decide_and_generate(i, item) for i, item in enumerate(items)])

        print(f"[STAGE3] All agent tasks complete. Viable bids per item: {', '.join(f'Item {i+1}: {len(item_bids[item.item_id])}' for i, item in enumerate(items))}")

        # ── Concurrency Waterfall ──
        total_wall = _time.time() - t2
        total_task_time = sum(t.get("elapsed", 0) for t in task_timings)
        concurrency_factor = total_task_time / total_wall if total_wall > 0 else 1

        print(f"\n[STAGE3] ═══ CONCURRENCY WATERFALL ═══════════════════════════════════")
        max_bar = 40
        max_elapsed = max((t.get("elapsed", 0.1) for t in task_timings), default=1)
        for t in sorted(task_timings, key=lambda x: x.get("start_offset", 0)):
            bar_len = int((t.get("elapsed", 0) / max_elapsed) * max_bar)
            offset_len = int((t.get("start_offset", 0) / total_wall) * max_bar) if total_wall > 0 else 0
            bar = " " * offset_len + "█" * max(bar_len, 1)
            bar = bar[:max_bar].ljust(max_bar)
            key_label = f"[Key {t['key']}]" if t.get('key') else "[local] "
            print(f"[STAGE3]  Item {t['item_idx']+1} {t['agent']:<22} |{bar}| {t.get('start_offset',0):.1f}s-{t.get('end_offset',0):.1f}s  {key_label}")

        print(f"[STAGE3]  {'─'*72}")
        print(f"[STAGE3]  Wall time: {total_wall:.1f}s | Sum of task times: {total_task_time:.1f}s | Concurrency: {concurrency_factor:.1f}x")
        print(f"[STAGE3] ═══════════════════════════════════════════════════════════════\n")

        await store.update_job_status(job_id, JobStatus.COMPLETED)
        total_time = _time.time() - t0
        print(f"\n[PIPELINE] ═══════════════════════════════════════════════════════════")
        print(f"[PIPELINE]  PIPELINE COMPLETE for job {job_id}")
        print(f"[PIPELINE]  Total time: {total_time:.1f}s")
        print(f"[PIPELINE]    Stage 1+2 (Extract+Analyze): {elapsed_fused/1000:.1f}s")
        print(f"[PIPELINE]    Stage 3+4 (Bid+Decide):     {_time.time()-t2:.1f}s")
        print(f"[PIPELINE]  Items: {len(items)} | Decisions: {len([r for r in results if not isinstance(r, Exception)])}")
        print(f"[PIPELINE]  WebSocket events broadcast: {manager._event_count}")
        print(f"[PIPELINE] ═══════════════════════════════════════════════════════════\n")

    except Exception as exc:
        print(f"[PIPELINE] ✗✗✗ Pipeline FAILED for job {job_id}: {exc}")
        import traceback
        traceback.print_exc()
        try:
            await store.update_job_status(job_id, JobStatus.FAILED, error=str(exc))
        except Exception:
            pass


async def _bid_trade_in(item: ItemCard) -> RouteBid:
    from backend.models.route_bid import TradeInQuote, EffortLevel, SpeedEstimate

    providers = [
        TradeInQuote(provider="Apple Trade In", payout=round(65 + item.confidence * 30, 2), speed="3-5 days", effort="low", confidence=0.8),
        TradeInQuote(provider="Best Buy", payout=round(50 + item.confidence * 25, 2), speed="instant", effort="minimal", confidence=0.85),
        TradeInQuote(provider="Decluttr", payout=round(40 + item.confidence * 20, 2), speed="2-3 days", effort="low", confidence=0.9),
        TradeInQuote(provider="Gazelle", payout=round(45 + item.confidence * 22, 2), speed="5-7 days", effort="low", confidence=0.75),
    ]
    for p in providers:
        p.payout = _clamp_value(p.payout, item.name_guess, "trade_in")
    best = max(providers, key=lambda q: q.payout)
    return RouteBid(
        item_id=item.item_id,
        route_type=RouteType.TRADE_IN,
        estimated_value=best.payout,
        effort=EffortLevel.LOW,
        speed=SpeedEstimate.DAYS,
        confidence=best.confidence,
        trade_in_quotes=providers,
        explanation=f"Best trade-in: {best.provider} at ${best.payout:.2f}",
    )


async def _bid_repair(item: ItemCard) -> RouteBid:
    from backend.services.amazon_api import AmazonService
    from backend.models.route_bid import EffortLevel, SpeedEstimate

    amazon = AmazonService()
    defect_query = f"{item.name_guess} replacement {item.all_defects[0].description}"
    parts = await amazon.search_parts(defect_query)
    if not parts:
        return RouteBid(
            item_id=item.item_id,
            route_type=RouteType.REPAIR_THEN_SELL,
            viable=False,
            explanation="No repair parts found",
        )
    repair_cost = sum(p.part_price for p in parts[:2])
    as_is_estimate = 50.0
    post_repair_estimate = as_is_estimate + repair_cost + 25.0
    final_value = round(post_repair_estimate * 0.87, 2)
    final_value = _clamp_value(final_value, item.name_guess, "marketplace")
    net_gain = post_repair_estimate - as_is_estimate - repair_cost
    return RouteBid(
        item_id=item.item_id,
        route_type=RouteType.REPAIR_THEN_SELL,
        estimated_value=final_value,
        effort=EffortLevel.HIGH,
        speed=SpeedEstimate.WEEKS,
        confidence=0.6,
        repair_candidates=parts,
        repair_cost=round(repair_cost, 2),
        as_is_value=as_is_estimate,
        post_repair_value=round(post_repair_estimate, 2),
        net_gain_unlocked=round(net_gain, 2),
        explanation=f"${repair_cost:.0f} repair unlocks ${net_gain:.0f} more value",
    )


async def _bid_return(item: ItemCard) -> RouteBid:
    from backend.models.route_bid import EffortLevel, SpeedEstimate

    is_returnable = (
        item.condition_label == "Like New"
        and item.confidence > 0.7
        and not item.has_defects
    )
    raw_value = round(item.confidence * 100, 2) if is_returnable else 0.0
    if is_returnable:
        raw_value = _clamp_value(raw_value, item.name_guess, "return")
    return RouteBid(
        item_id=item.item_id,
        route_type=RouteType.RETURN,
        viable=is_returnable,
        estimated_value=raw_value,
        effort=EffortLevel.MINIMAL,
        speed=SpeedEstimate.DAYS,
        confidence=0.7 if is_returnable else 0.1,
        return_window_open=is_returnable,
        explanation="Item appears new/unused — return likely viable" if is_returnable else "Item shows wear, return unlikely",
    )


def _decide_best_route(
    item_id: str, bids: list[RouteBid]
) -> BestRouteDecision:
    viable = [b for b in bids if b.viable]
    if not viable:
        return BestRouteDecision(
            item_id=item_id,
            best_route=RouteType.NO_ACTION,
            route_reason="No viable routes found",
            alternatives=bids,
        )

    def _score(bid: RouteBid) -> float:
        effort_map = {"minimal": 1.0, "low": 0.8, "moderate": 0.5, "high": 0.2}
        speed_map = {"instant": 1.0, "days": 0.8, "week": 0.5, "weeks": 0.3, "month_plus": 0.1}
        max_value = max((b.estimated_value for b in viable), default=0)
        value_norm = bid.estimated_value / max_value if max_value > 0 else 0
        return (
            0.45 * value_norm
            + 0.25 * bid.confidence
            + 0.15 * effort_map.get(bid.effort.value, 0.5)
            + 0.15 * speed_map.get(bid.speed.value, 0.5)
        )

    scored = sorted(viable, key=_score, reverse=True)
    winner = scored[0]

    return BestRouteDecision(
        item_id=item_id,
        best_route=winner.route_type,
        estimated_best_value=winner.estimated_value,
        effort=winner.effort,
        speed=winner.speed,
        winning_bid=winner,
        route_reason=winner.explanation,
        route_explanation_short=f"{winner.route_type.value.replace('_', ' ').title()} wins — ${winner.estimated_value:.0f}",
        route_explanation_detailed=f"Chose {winner.route_type.value} with estimated ${winner.estimated_value:.2f} "
            f"(confidence {winner.confidence:.0%}, effort {winner.effort.value}, speed {winner.speed.value}). "
            f"{winner.explanation}",
        alternatives=bids,
    )


async def run_execution(job_id: str, item_id: str, platforms: list[str]) -> None:
    print(f"[EXECUTE] Starting execution for item={item_id} platforms={platforms}")
    try:
        await store.update_job_status(job_id, JobStatus.EXECUTING)

        listing = store.get_listing(item_id)
        if not listing:
            print(f"[EXECUTE] ✗ No listing package for item {item_id} — was the pipeline completed?")
            logger.error("No listing package for item %s", item_id)
            await store.update_job_status(job_id, JobStatus.COMPLETED)
            return

        print(f"[EXECUTE] Found listing: '{listing.title}' price=${listing.price_strategy} images={len(listing.images)}")

        from backend.systems.execution import ExecutionSystem

        executor = ExecutionSystem()
        result = await executor.execute(listing, platforms)

        live = [pl for pl in result.platform_listings if pl.status == PlatformStatus.LIVE]
        failed = [pl for pl in result.platform_listings if pl.status == PlatformStatus.FAILED]
        print(f"[EXECUTE] ✓ Done — {len(live)} live, {len(failed)} failed")
        for pl in result.platform_listings:
            print(f"[EXECUTE]   {pl.platform}: {pl.status.value} url={pl.url or '—'} error={pl.error or '—'}")

        await store.update_job_status(job_id, JobStatus.COMPLETED)
    except Exception as exc:
        print(f"[EXECUTE] ✗✗✗ Execution FAILED for item {item_id}: {exc}")
        logger.exception("Execution failed for item %s: %s", item_id, exc)
        try:
            await store.update_job_status(job_id, JobStatus.FAILED, error=str(exc))
        except Exception:
            pass


# ── Static File Mounts ───────────────────────────────────────────────────────

settings.ensure_dirs()

_listing_imgs_dir = str(Path(__file__).resolve().parent / ".reroutecache" / "listing_images")

for _mount, _directory in [
    ("/frames", settings.frames_dir),
    ("/optimized", settings.optimized_dir),
    ("/uploads", settings.upload_dir),
    ("/listing-images", _listing_imgs_dir),
]:
    Path(_directory).mkdir(parents=True, exist_ok=True)
    app.mount(_mount, StaticFiles(directory=_directory), name=_mount.lstrip("/"))

_phone_dir = Path("frontend/phone")
if _phone_dir.is_dir():
    app.mount("/phone", StaticFiles(directory=str(_phone_dir), html=True), name="phone")

_mac_dist = Path("frontend/mac/dist")
if _mac_dist.is_dir():
    app.mount(
        "/", StaticFiles(directory=str(_mac_dist), html=True), name="mac-dashboard"
    )
