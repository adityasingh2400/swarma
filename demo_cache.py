"""Demo cache — pre-recorded results for the 3-item demo video.

When DEMO_MODE is active AND items match known demo items, the orchestrator
replays cached research results and screenshot frames instead of launching
real browser agents. The frontend sees identical events with consistent timing.

For unknown items (judge's single item), the real pipeline runs normally.
"""
from __future__ import annotations

import asyncio
import base64
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

# ── Known demo items and their cached research results ────────────────────────
# Keys are lowercase substrings that match item.name_guess from intake.

RESEARCH_CACHE: dict[str, dict[str, dict]] = {
    "whxm": {
        "facebook": {"avg_sold_price": 150.0, "listings_found": 20, "price_type": "active"},
        "depop":    {"avg_sold_price": 185.0, "listings_found": 8, "price_type": "active"},
        "amazon":   {"avg_sold_price": 0.0, "parts": [
            {"part_name": "Replacement Earpads for WH-1000XM4", "part_price": 10.88, "part_url": "#"},
            {"part_name": "Headband Replacement WH-1000XM4", "part_price": 38.95, "part_url": "#"},
            {"part_name": "USB Charging Port Replacement", "part_price": 18.69, "part_url": "#"},
        ]},
    },
    "takis": {
        "facebook": {"avg_sold_price": 12.0, "listings_found": 72, "price_type": "active"},
        "depop":    {"avg_sold_price": 11.0, "listings_found": 25, "price_type": "active"},
        "amazon":   {"avg_sold_price": 0.0, "parts": [
            {"part_name": "Takis Fuego 40 Count Multipack", "part_price": 25.99, "part_url": "#"},
            {"part_name": "Takis Fuego Mini 25pc", "part_price": 17.29, "part_url": "#"},
        ]},
    },
    "hoodie": {
        "facebook": {"avg_sold_price": 15.0, "listings_found": 57, "price_type": "active"},
        "depop":    {"avg_sold_price": 28.0, "listings_found": 67000, "price_type": "active"},
        "amazon":   {"avg_sold_price": 0.0, "parts": [
            {"part_name": "Mandala Crafts Drawstring Cord Replacement", "part_price": 9.99, "part_url": "#"},
            {"part_name": "uxcell Drawstring Cords Replacement Green", "part_price": 5.69, "part_url": "#"},
        ]},
    },
}

PLATFORMS = ["facebook", "depop", "amazon"]

# ── Placeholder screenshot (1x1 gray JPEG) — used until real frames arrive ───
_PLACEHOLDER_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkS"
    "Ew8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJ"
    "CQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf"
    "/EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAA"
    "AAAAAAAAP/aAAwDAQACEQMRAD8AKwA//9k="
)


def match_demo_item(item: ItemCard) -> str | None:
    """Return the cache key if this item matches a known demo item, else None."""
    name = (item.name_guess or "").lower()
    for key in RESEARCH_CACHE:
        if key in name:
            return key
    return None


def is_full_demo(items: list[ItemCard]) -> bool:
    """True if ALL items match known demo cache entries."""
    return len(items) > 0 and all(match_demo_item(it) is not None for it in items)


def _build_listing_package(item: ItemCard, decision: RouteDecision, research: dict, job_id: str) -> ListingPackage:
    """Build a listing package from cached research (mirrors orchestrator logic)."""
    from config import settings as cfg

    title = item.name_guess or "Item"
    condition = getattr(item, "condition_label", None) or "Like New"

    research_prices = [
        data.get("avg_sold_price", 0.0)
        for data in research.values()
        if data.get("avg_sold_price", 0) > 0
    ]
    if research_prices:
        price = round(sum(research_prices) / len(research_prices) * 0.95)
    else:
        price = 0.0

    img_dir = Path(cfg.listing_images_dir) / item.item_id
    images = []
    if img_dir.exists():
        for p in sorted(img_dir.glob("photo_*.jpg"))[:6]:
            images.append(ListingImage(path=str(p)))

    desc = f"{title}\n\nCondition: {condition}.\n\nShips quickly. Message with questions!"

    return ListingPackage(
        item_id=item.item_id,
        title=title,
        description=desc,
        price_strategy=price,
        price_min=round(price * 0.85) if price else 0,
        price_max=round(price * 1.05) if price else 0,
        condition_summary=condition,
        images=images,
    )


async def run_cached_pipeline(
    orchestrator,
    job_id: str,
    items: list[ItemCard],
) -> None:
    """Replay cached research + listing for known demo items.

    Emits the same events as the real pipeline with realistic timing.
    The frontend can't tell the difference.
    """
    emit = orchestrator._emit
    agent_states = orchestrator.agent_states

    swarma_line("demo_cache", "start", job_id=job_id, items_n=len(items))

    # ── 1. Advertise agents (instant) ──
    agent_plan = []
    for item in items:
        for platform in PLATFORMS:
            agent_id = f"{platform}-research-{item.item_id}"
            agent_plan.append((item, platform, agent_id))
            agent_states[agent_id] = AgentState(
                agent_id=agent_id, item_id=item.item_id,
                platform=platform, phase="research",
                status="ready", task=f"research {platform} for {item.name_guess}",
            )
            emit(AgentEvent(type="agent:spawn", agent_id=agent_id, data={
                "platform": platform, "phase": "research",
                "item_id": item.item_id, "task": agent_states[agent_id].task,
                "status": "ready",
            }))

    await asyncio.sleep(0.3)

    # ── 2. Simulate preload (feed placeholder screenshots + mark preloaded) ──
    for item, platform, agent_id in agent_plan:
        streaming.frame_store[agent_id] = streaming.FrameData(
            jpeg=_PLACEHOLDER_JPEG, ts=time.time()
        )
        agent_states[agent_id].status = "preloaded"
        emit(AgentEvent(type="agent:status", agent_id=agent_id, data={"status": "preloaded"}))

    await asyncio.sleep(0.5)

    # ── 3. Research phase (staggered results with realistic timing) ──
    for item, platform, agent_id in agent_plan:
        agent_states[agent_id].status = "running"
        agent_states[agent_id].started_at = time.time()
        emit(AgentEvent(type="agent:spawn", agent_id=agent_id, data={
            "platform": platform, "phase": "research",
            "item_id": item.item_id, "task": agent_states[agent_id].task,
        }))

    # Stagger completions over ~8-15 seconds for realism
    async def _complete_research(item: ItemCard, platform: str, agent_id: str, delay: float):
        await asyncio.sleep(delay)
        cache_key = match_demo_item(item)
        result = RESEARCH_CACHE.get(cache_key, {}).get(platform, {})

        agent_states[agent_id].status = "complete"
        agent_states[agent_id].completed_at = time.time()
        agent_states[agent_id].result = result
        emit(AgentEvent(type="agent:result", agent_id=agent_id, data={"final_result": str(result)}))
        emit(AgentEvent(type="agent:complete", agent_id=agent_id, data={
            "duration_s": delay,
        }))
        swarma_line("demo_cache", "research_done", agent_id=agent_id, platform=platform)

    tasks = []
    base_delay = 8.0
    for i, (item, platform, agent_id) in enumerate(agent_plan):
        delay = base_delay + (i * 1.2)  # stagger: 8s, 9.2s, 10.4s, ...
        tasks.append(_complete_research(item, platform, agent_id, delay))

    await asyncio.gather(*tasks)

    # ── 4. Route decisions + listing packages ──
    for item in items:
        cache_key = match_demo_item(item)
        cached = RESEARCH_CACHE.get(cache_key, {})
        decision = route_decision(item, cached)

        emit(AgentEvent(type="decision:made", agent_id=f"decision-{item.item_id}", data={
            "item_id": item.item_id,
            "platforms": decision.platforms,
            "prices": decision.prices,
            "scores": decision.scores,
        }))

        pkg = _build_listing_package(item, decision, cached, job_id)
        item.listing_package = pkg

        swarma_line("demo_cache", "decision", item=item.name_guess,
                    platforms=decision.platforms, price=pkg.price_strategy)

    await asyncio.sleep(1.0)

    # ── 5. Listing phase (stagger completions over ~20-40s for realism) ──
    listing_agents = []
    for item in items:
        agent_id = f"facebook-listing-{item.item_id}"
        listing_agents.append((item, agent_id))
        agent_states[agent_id] = AgentState(
            agent_id=agent_id, item_id=item.item_id,
            platform="facebook", phase="listing",
            status="running", task=f"listing facebook for {item.name_guess}",
            started_at=time.time(),
        )
        emit(AgentEvent(type="agent:spawn", agent_id=agent_id, data={
            "platform": "facebook", "phase": "listing",
            "item_id": item.item_id, "task": agent_states[agent_id].task,
        }))
        # Feed a placeholder frame so the posting page has something to show
        streaming.frame_store[agent_id] = streaming.FrameData(
            jpeg=_PLACEHOLDER_JPEG, ts=time.time()
        )

    async def _complete_listing(item: ItemCard, agent_id: str, delay: float):
        await asyncio.sleep(delay)
        agent_states[agent_id].status = "complete"
        agent_states[agent_id].completed_at = time.time()
        emit(AgentEvent(type="agent:result", agent_id=agent_id, data={
            "final_result": f"Successfully listed '{item.name_guess}' on Facebook Marketplace.",
        }))
        emit(AgentEvent(type="agent:complete", agent_id=agent_id, data={
            "duration_s": delay,
        }))
        swarma_line("demo_cache", "listing_done", agent_id=agent_id, item=item.name_guess)

    listing_tasks = []
    for i, (item, agent_id) in enumerate(listing_agents):
        delay = 25.0 + (i * 15.0)  # 25s, 40s, 55s — realistic listing times
        listing_tasks.append(_complete_listing(item, agent_id, delay))

    await asyncio.gather(*listing_tasks)

    swarma_line("demo_cache", "pipeline_complete", job_id=job_id)
