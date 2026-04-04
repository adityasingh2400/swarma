"""In-memory job store with JSON persistence for hackathon demo.
Copied from v1 with import paths updated."""
from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Callable, Awaitable

from config import settings
from models.job import Job, JobStatus
from models.item_card import ItemCard
from models.route_bid import RouteBid, BestRouteDecision
from models.listing_package import ListingPackage
from models.conversation import ConversationThread

EventCallback = Callable[[str, dict], Awaitable[None]]


def _to_url(fs_path: str) -> str:
    name = Path(fs_path).name
    low = fs_path.replace("\\", "/")
    if "/frames/" in low:
        return f"/frames/{name}"
    if "/optimized/" in low:
        return f"/optimized/{name}"
    if "/uploads/" in low:
        return f"/uploads/{name}"
    return fs_path


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._items: dict[str, ItemCard] = {}
        self._bids: dict[str, list[RouteBid]] = {}
        self._decisions: dict[str, BestRouteDecision] = {}
        self._listings: dict[str, ListingPackage] = {}
        self._threads: dict[str, ConversationThread] = {}
        self._agent_states: dict[str, dict[str, dict]] = {}
        self._event_callbacks: list[EventCallback] = []
        self._persist_dir = Path(settings.jobs_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    def on_event(self, callback: EventCallback) -> None:
        self._event_callbacks.append(callback)

    async def _emit(self, event_type: str, data: dict) -> None:
        for cb in self._event_callbacks:
            try:
                await cb(event_type, data)
            except Exception:
                pass

    async def create_job(self, video_path: str) -> Job:
        job = Job(video_path=video_path)
        self._jobs[job.job_id] = job
        self._persist_job(job)
        await self._emit("job_created", job.model_dump(mode="json"))
        return job

    async def update_job_status(self, job_id: str, status: JobStatus, **kwargs) -> Job:
        job = self._jobs[job_id]
        job.status = status
        for k, v in kwargs.items():
            if hasattr(job, k):
                setattr(job, k, v)
        job.touch()
        self._persist_job(job)
        await self._emit("job_updated", {"job_id": job_id, "status": status.value, **kwargs})
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def add_item(self, item: ItemCard) -> None:
        self._items[item.item_id] = item
        if item.job_id and item.job_id in self._jobs:
            job = self._jobs[item.job_id]
            if item.item_id not in job.item_ids:
                job.item_ids.append(item.item_id)
                job.touch()
        await self._emit("item_added", item.model_dump(mode="json"))

    def get_item(self, item_id: str) -> ItemCard | None:
        return self._items.get(item_id)

    def get_items_for_job(self, job_id: str) -> list[ItemCard]:
        return [i for i in self._items.values() if i.job_id == job_id]

    async def add_bid(self, bid: RouteBid) -> None:
        self._bids.setdefault(bid.item_id, []).append(bid)
        await self._emit("bid_added", bid.model_dump(mode="json"))

    def get_bids(self, item_id: str) -> list[RouteBid]:
        return self._bids.get(item_id, [])

    async def set_decision(self, decision: BestRouteDecision) -> None:
        self._decisions[decision.item_id] = decision
        await self._emit("decision_made", decision.model_dump(mode="json"))

    def get_decision(self, item_id: str) -> BestRouteDecision | None:
        return self._decisions.get(item_id)

    async def set_listing(self, listing: ListingPackage) -> None:
        self._listings[listing.item_id] = listing
        await self._emit("listing_updated", listing.model_dump(mode="json"))

    def get_listing(self, item_id: str) -> ListingPackage | None:
        return self._listings.get(item_id)

    async def add_thread(self, thread: ConversationThread) -> None:
        self._threads[thread.thread_id] = thread
        await self._emit("thread_updated", thread.model_dump(mode="json"))

    def get_thread(self, thread_id: str) -> ConversationThread | None:
        return self._threads.get(thread_id)

    def get_threads_for_item(self, item_id: str) -> list[ConversationThread]:
        return [t for t in self._threads.values() if t.item_id == item_id]

    def get_full_state(self, job_id: str) -> dict:
        job = self.get_job(job_id)
        if not job:
            return {}
        items = self.get_items_for_job(job_id)
        job_data = job.model_dump(mode="json")
        if job.video_path:
            job_data["video_url"] = _to_url(job.video_path)
        return {
            "job": job_data,
            "items": [i.model_dump(mode="json") for i in items],
            "bids": {
                iid: [b.model_dump(mode="json") for b in self.get_bids(iid)]
                for iid in job.item_ids
            },
            "decisions": {
                iid: d.model_dump(mode="json")
                for iid in job.item_ids
                if (d := self.get_decision(iid))
            },
            "listings": {
                iid: l.model_dump(mode="json")
                for iid in job.item_ids
                if (l := self.get_listing(iid))
            },
            "threads": {
                iid: [t.model_dump(mode="json") for t in self.get_threads_for_item(iid)]
                for iid in job.item_ids
            },
        }

    def _persist_job(self, job: Job) -> None:
        path = self._persist_dir / f"{job.job_id}.json"
        path.write_text(job.model_dump_json(indent=2))


store = JobStore()
