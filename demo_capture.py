"""Demo capture — records a live pipeline run for later replay.

Run the pipeline normally. This module captures:
  1. Screenshot JPEG frames per agent (sampled at ~2fps from frame_store)
  2. Final research results per agent
  3. Final listing results per agent
  4. Event timeline with timestamps
  5. Item metadata (name, condition, images)

All saved to data/demo-cache/ for use by demo_cache.py replay.

Usage: set DEMO_CAPTURE=true in .env or environment before running.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import backend.streaming as streaming

logger = logging.getLogger("swarmsell.demo_capture")

CACHE_DIR = Path("data/demo-cache")
CAPTURE_ENABLED = os.environ.get("DEMO_CAPTURE", "").lower() in ("true", "1", "yes")

_capture_task: asyncio.Task | None = None
_events_log: list[dict] = []
_results: dict[str, dict] = {}   # agent_id -> {"final_result": ..., "phase": ..., "platform": ...}
_frame_counts: dict[str, int] = {}


def start_capture(job_id: str, items: list) -> None:
    """Begin capturing. Call this right before the pipeline starts."""
    if not CAPTURE_ENABLED:
        return

    global _capture_task, _events_log, _results, _frame_counts
    _events_log = []
    _results = {}
    _frame_counts = {}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Save item metadata
    items_data = []
    for item in items:
        items_data.append({
            "item_id": item.item_id,
            "name_guess": item.name_guess,
            "condition": getattr(item, "condition_label", None) or getattr(item, "condition", ""),
            "hero_frame_paths": getattr(item, "hero_frame_paths", []),
            "listing_image_paths": getattr(item, "listing_image_paths", []),
            "category": getattr(item, "category", None),
        })
    (CACHE_DIR / "items.json").write_text(json.dumps(items_data, indent=2, default=str))

    # Start frame capture loop
    _capture_task = asyncio.ensure_future(_frame_capture_loop(job_id))
    logger.info("Demo capture started for job %s — saving to %s", job_id, CACHE_DIR)


def capture_event(event_dict: dict) -> None:
    """Record a WS event for the timeline."""
    if not CAPTURE_ENABLED:
        return
    _events_log.append({
        "ts": time.time(),
        "type": event_dict.get("type"),
        "agent_id": event_dict.get("agent_id") or event_dict.get("data", {}).get("agent_id"),
        "data": event_dict.get("data", {}),
    })

    # Capture final results
    if event_dict.get("type") == "agent:result":
        agent_id = event_dict.get("agent_id", "")
        data = event_dict.get("data", {})
        _results[agent_id] = {
            "final_result": data.get("final_result"),
            "ts": time.time(),
        }


async def _frame_capture_loop(job_id: str) -> None:
    """Periodically snapshot frame_store to disk at ~2fps."""
    frames_dir = CACHE_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    try:
        while True:
            for agent_id, frame_data in list(streaming.frame_store.items()):
                agent_dir = frames_dir / agent_id.replace("/", "_")
                agent_dir.mkdir(parents=True, exist_ok=True)

                count = _frame_counts.get(agent_id, 0)
                frame_path = agent_dir / f"frame_{count:04d}.jpg"
                frame_path.write_bytes(frame_data.jpeg)
                _frame_counts[agent_id] = count + 1

            await asyncio.sleep(0.5)  # ~2fps capture rate
    except asyncio.CancelledError:
        pass


def stop_capture() -> None:
    """Stop capturing and save all collected data."""
    if not CAPTURE_ENABLED:
        return

    global _capture_task
    if _capture_task and not _capture_task.done():
        _capture_task.cancel()
    _capture_task = None

    # Save events timeline
    (CACHE_DIR / "events.json").write_text(json.dumps(_events_log, indent=2, default=str))

    # Save research/listing results
    (CACHE_DIR / "results.json").write_text(json.dumps(_results, indent=2, default=str))

    # Save frame counts summary
    summary = {
        "frame_counts": _frame_counts,
        "total_frames": sum(_frame_counts.values()),
        "agents_captured": list(_frame_counts.keys()),
        "results_captured": list(_results.keys()),
        "events_captured": len(_events_log),
    }
    (CACHE_DIR / "capture_summary.json").write_text(json.dumps(summary, indent=2))

    logger.info(
        "Demo capture saved: %d frames across %d agents, %d results, %d events",
        sum(_frame_counts.values()), len(_frame_counts),
        len(_results), len(_events_log),
    )
