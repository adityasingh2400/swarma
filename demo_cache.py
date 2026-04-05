"""Demo cache — replays a pre-recorded pipeline run for the 3-item demo video.

When all items match known demo entries, replays captured screenshot frames
and research results with realistic timing. No real browsers launched.

For unknown items (judge's single item), the real pipeline runs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from contracts import AgentEvent, AgentState, RouteDecision
from models.item_card import ItemCard
from models.listing_package import ListingPackage, ListingImage
from route_decision import route_decision
import backend.streaming as streaming

logger = logging.getLogger("swarmsell.demo_cache")

try:
    from backend.debug_trace import swarma_line
except ImportError:
    def swarma_line(component, event, **fields):
        pass

CACHE_DIR = Path("data/demo-cache")
FRAMES_DIR = CACHE_DIR / "frames"
PLATFORMS = ["facebook", "depop", "amazon"]

# ── Match items to cached data ────────────────────────────────────────────────
# Substrings to match against item.name_guess
_DEMO_KEYS = ["whxm", "takis", "hoodie"]


def match_demo_item(item: ItemCard) -> str | None:
    name = (item.name_guess or "").lower()
    for key in _DEMO_KEYS:
        if key in name:
            return key
    return None


def is_full_demo(items: list[ItemCard]) -> bool:
    return len(items) > 0 and all(match_demo_item(it) is not None for it in items)


def _load_cached_results() -> dict[str, str]:
    """Load agent_results.json — maps agent_id to final_result string."""
    path = CACHE_DIR / "agent_results.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _load_cached_items() -> list[dict]:
    """Load items.json from capture."""
    path = CACHE_DIR / "items.json"
    if path.exists():
        return json.loads(path.read_text())
    return []


def _get_frame_files(agent_id: str) -> list[Path]:
    """Get sorted JPEG frame files for an agent."""
    agent_dir = FRAMES_DIR / agent_id.replace("/", "_")
    if not agent_dir.exists():
        return []
    return sorted(agent_dir.glob("frame_*.jpg"))


def _parse_research_from_result(result_str: str) -> dict:
    """Parse cached research result string into structured dict."""
    from playbooks.base import BasePlaybook
    # Use a temporary instance just for parsing
    pb = BasePlaybook.__new__(BasePlaybook)
    pb.platform = "unknown"
    try:
        return pb._parse_price_list_research(result_str, price_type="active")
    except Exception:
        return {"avg_sold_price": 0.0, "listings_found": 0}


def _build_listing_package(item: ItemCard, decision: RouteDecision, research: dict, job_id: str) -> ListingPackage:
    from config import settings as cfg

    title = item.name_guess or "Item"
    condition = getattr(item, "condition_label", None) or getattr(item, "condition", "") or "Like New"

    research_prices = [
        data.get("avg_sold_price", 0.0)
        for data in research.values()
        if data.get("avg_sold_price", 0) > 0
    ]
    price = round(sum(research_prices) / len(research_prices) * 0.95) if research_prices else 0.0

    img_dir = Path(cfg.listing_images_dir) / item.item_id
    images = []
    if img_dir.exists():
        for p in sorted(img_dir.glob("photo_*.jpg"))[:6]:
            images.append(ListingImage(path=str(p)))

    desc = f"{title}\n\nCondition: {condition}.\n\nShips quickly. Message with questions!"

    return ListingPackage(
        item_id=item.item_id, title=title, description=desc,
        price_strategy=price, price_min=round(price * 0.85) if price else 0,
        price_max=round(price * 1.05) if price else 0,
        condition_summary=condition, images=images,
    )


def _find_cached_agent(platform: str, phase: str, demo_key: str) -> str | None:
    """Find the captured agent_id that matches this platform+phase+demo_key."""
    cached_items = _load_cached_items()
    for ci in cached_items:
        name = (ci.get("name_guess") or "").lower()
        if demo_key in name:
            cid = ci["item_id"]
            if phase == "concierge":
                candidate = f"fb-concierge-{cid[:8]}"
            else:
                candidate = f"{platform}-{phase}-{cid}"
            if _get_frame_files(candidate):
                return candidate
    return None


async def _replay_frames(agent_id: str, cached_agent_id: str, fps: float = 3.0) -> None:
    """Replay captured JPEG frames into frame_store at the given fps."""
    frames = _get_frame_files(cached_agent_id)
    if not frames:
        return
    delay = 1.0 / fps
    for frame_path in frames:
        jpeg = frame_path.read_bytes()
        streaming.frame_store[agent_id] = streaming.FrameData(jpeg=jpeg, ts=time.time())
        await asyncio.sleep(delay)


async def run_cached_pipeline(
    orchestrator,
    job_id: str,
    items: list[ItemCard],
) -> None:
    """Replay cached frames + results for known demo items."""
    emit = orchestrator._emit
    states = orchestrator.agent_states
    cached_results = _load_cached_results()

    swarma_line("demo_cache", "start", job_id=job_id, items_n=len(items))

    # ── 1. Advertise research agents ──
    research_plan = []  # (item, platform, agent_id, cached_agent_id)
    for item in items:
        demo_key = match_demo_item(item)
        for platform in PLATFORMS:
            agent_id = f"{platform}-research-{item.item_id}"
            cached_aid = _find_cached_agent(platform, "research", demo_key)
            research_plan.append((item, platform, agent_id, cached_aid))
            states[agent_id] = AgentState(
                agent_id=agent_id, item_id=item.item_id,
                platform=platform, phase="research",
                status="ready", task=f"research {platform} for {item.name_guess}",
            )
            emit(AgentEvent(type="agent:spawn", agent_id=agent_id, data={
                "platform": platform, "phase": "research",
                "item_id": item.item_id, "task": states[agent_id].task,
                "status": "ready",
            }))

    await asyncio.sleep(0.3)

    # ── 2. Preload — mark preloaded + start frame replay for all research agents ──
    replay_tasks = []
    for item, platform, agent_id, cached_aid in research_plan:
        states[agent_id].status = "preloaded"
        emit(AgentEvent(type="agent:status", agent_id=agent_id, data={"status": "preloaded"}))
        if cached_aid:
            replay_tasks.append(_replay_frames(agent_id, cached_aid, fps=3.0))

    # Start all frame replays concurrently (they run in background)
    frame_runners = [asyncio.ensure_future(t) for t in replay_tasks]

    await asyncio.sleep(0.5)

    # ── 3. Research — mark running, wait, then complete with cached results ──
    for item, platform, agent_id, cached_aid in research_plan:
        states[agent_id].status = "running"
        states[agent_id].started_at = time.time()
        emit(AgentEvent(type="agent:spawn", agent_id=agent_id, data={
            "platform": platform, "phase": "research",
            "item_id": item.item_id, "task": states[agent_id].task,
        }))

    async def _finish_research(item, platform, agent_id, cached_aid, delay):
        await asyncio.sleep(delay)
        # Get cached result
        result_str = cached_results.get(cached_aid, "{}") if cached_aid else "{}"
        states[agent_id].status = "complete"
        states[agent_id].completed_at = time.time()
        emit(AgentEvent(type="agent:result", agent_id=agent_id, data={"final_result": result_str}))
        emit(AgentEvent(type="agent:complete", agent_id=agent_id, data={"duration_s": delay}))

    research_tasks = []
    for i, (item, platform, agent_id, cached_aid) in enumerate(research_plan):
        delay = 8.0 + (i * 1.5)
        research_tasks.append(_finish_research(item, platform, agent_id, cached_aid, delay))

    await asyncio.gather(*research_tasks)

    # ── 4. Route decisions ──
    for item in items:
        demo_key = match_demo_item(item)
        parsed = {}
        for platform in PLATFORMS:
            cached_aid = _find_cached_agent(platform, "research", demo_key)
            result_str = cached_results.get(cached_aid, "{}") if cached_aid else "{}"
            parsed[platform] = _parse_research_from_result(result_str)

        decision = route_decision(item, parsed)
        emit(AgentEvent(type="decision:made", agent_id=f"decision-{item.item_id}", data={
            "item_id": item.item_id,
            "platforms": decision.platforms,
            "prices": decision.prices,
            "scores": decision.scores,
        }))

        pkg = _build_listing_package(item, decision, parsed, job_id)
        item.listing_package = pkg
        swarma_line("demo_cache", "decision", item=item.name_guess, price=pkg.price_strategy)

    await asyncio.sleep(1.0)

    # ── 5. Listing — spawn, replay frames, complete ──
    listing_plan = []
    for item in items:
        demo_key = match_demo_item(item)
        agent_id = f"facebook-listing-{item.item_id}"
        cached_aid = _find_cached_agent("facebook", "listing", demo_key)
        listing_plan.append((item, agent_id, cached_aid))
        states[agent_id] = AgentState(
            agent_id=agent_id, item_id=item.item_id,
            platform="facebook", phase="listing",
            status="running", task=f"listing facebook for {item.name_guess}",
            started_at=time.time(),
        )
        emit(AgentEvent(type="agent:spawn", agent_id=agent_id, data={
            "platform": "facebook", "phase": "listing",
            "item_id": item.item_id, "task": states[agent_id].task,
        }))
        if cached_aid:
            asyncio.ensure_future(_replay_frames(agent_id, cached_aid, fps=2.0))

    async def _finish_listing(item, agent_id, cached_aid, delay):
        await asyncio.sleep(delay)
        result_str = cached_results.get(cached_aid, f"Listed '{item.name_guess}' on Facebook.") if cached_aid else ""
        states[agent_id].status = "complete"
        states[agent_id].completed_at = time.time()
        emit(AgentEvent(type="agent:result", agent_id=agent_id, data={"final_result": result_str}))
        emit(AgentEvent(type="agent:complete", agent_id=agent_id, data={"duration_s": delay}))

    listing_tasks = []
    for i, (item, agent_id, cached_aid) in enumerate(listing_plan):
        delay = 25.0 + (i * 12.0)
        listing_tasks.append(_finish_listing(item, agent_id, cached_aid, delay))

    await asyncio.gather(*listing_tasks)

    # Cancel any still-running frame replays
    for t in frame_runners:
        if not t.done():
            t.cancel()

    swarma_line("demo_cache", "pipeline_complete", job_id=job_id)
