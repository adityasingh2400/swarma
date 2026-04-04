from __future__ import annotations

import logging

from backend.models.listing_package import PlatformStatus
from backend.storage.store import store

logger = logging.getLogger(__name__)


class RouteCloserSystem:
    def __init__(self) -> None:
        self._adapters: dict = {}

    def register_adapters(self, adapters: dict) -> None:
        self._adapters = adapters

    async def close_losing_routes(
        self,
        item_id: str,
        winning_platform: str,
    ) -> None:
        listing = store.get_listing(item_id)
        if not listing:
            logger.warning("No listing found for item %s", item_id)
            return

        for pl in listing.platform_listings:
            if pl.platform == winning_platform:
                continue
            if pl.status not in (PlatformStatus.LIVE, PlatformStatus.PUBLISHING):
                continue

            try:
                await self.archive_listing(pl.platform, pl.platform_listing_id)
                pl.status = PlatformStatus.ARCHIVED
                logger.info(
                    "Archived %s listing %s for item %s (winner: %s)",
                    pl.platform,
                    pl.platform_listing_id,
                    item_id,
                    winning_platform,
                )
            except Exception:
                logger.exception(
                    "Failed to archive %s listing %s",
                    pl.platform,
                    pl.platform_listing_id,
                )

        await store.set_listing(listing)

    async def archive_listing(self, platform: str, listing_id: str) -> bool:
        adapter = self._adapters.get(platform)
        if adapter is None:
            logger.warning("No adapter for platform=%s, skipping archive", platform)
            return False

        try:
            return await adapter.archive(listing_id)
        except Exception:
            logger.exception("Archive failed for %s/%s", platform, listing_id)
            return False

    async def mark_resolved(self, item_id: str, recovered_value: float) -> None:
        job_id = ""
        item = store.get_item(item_id)
        if item:
            job_id = item.job_id

        if job_id:
            job = store.get_job(job_id)
            if job:
                job.total_recovered_value += recovered_value
                job.touch()

        listing = store.get_listing(item_id)
        if listing:
            for pl in listing.platform_listings:
                if pl.status == PlatformStatus.LIVE:
                    pl.status = PlatformStatus.ARCHIVED
            await store.set_listing(listing)

        logger.info(
            "Item %s resolved: recovered $%.2f",
            item_id,
            recovered_value,
        )
