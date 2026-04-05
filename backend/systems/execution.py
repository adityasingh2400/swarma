from __future__ import annotations

import asyncio
import logging

from backend.adapters.base import PlatformAdapter
from backend.models.listing_package import ListingPackage, PlatformListing, PlatformStatus
from backend.storage.store import store

logger = logging.getLogger(__name__)


class ExecutionSystem:
    """Publishes listings to multiple platforms concurrently.

    Execution flow (concurrent):
      asyncio.gather(*[_execute_single(p) for p in platforms])
          ↓
      Collect PlatformListing results (or exceptions)
          ↓
      Append all results to package.platform_listings sequentially
          ↓
      Single store.set_listing() call at the end
    """

    def __init__(self, adapters: dict[str, PlatformAdapter] | None = None) -> None:
        self._adapters: dict[str, PlatformAdapter] = adapters or {}

    def register_adapter(self, name: str, adapter: PlatformAdapter) -> None:
        self._adapters[name] = adapter

    async def execute(
        self,
        package: ListingPackage,
        platforms: list[str],
    ) -> ListingPackage:
        # Clear previous failed attempts so they don't accumulate
        package.platform_listings = [
            pl for pl in package.platform_listings
            if pl.status in (PlatformStatus.LIVE, PlatformStatus.ARCHIVED)
        ]

        async def _execute_single(platform: str) -> PlatformListing:
            existing = next(
                (pl for pl in package.platform_listings
                 if pl.platform == platform and pl.status == PlatformStatus.LIVE),
                None,
            )
            if existing:
                logger.info("Skipping %s — already live", platform)
                return existing

            adapter = self._adapters.get(platform)
            if adapter is None:
                logger.warning("No adapter registered for platform=%s", platform)
                return PlatformListing(
                    platform=platform,
                    status=PlatformStatus.SKIPPED,
                    error=f"No adapter for {platform}",
                )
            draft = await adapter.create_draft(package)
            return await adapter.publish(draft)

        results = await asyncio.gather(
            *[_execute_single(p) for p in platforms],
            return_exceptions=True,
        )

        for platform, result in zip(platforms, results):
            if isinstance(result, Exception):
                logger.error("Execution failed for platform=%s: %s", platform, result, exc_info=result)
                package.platform_listings.append(PlatformListing(
                    platform=platform,
                    status=PlatformStatus.FAILED,
                    error=f"Execution error on {platform}",
                ))
            else:
                if not any(pl is result for pl in package.platform_listings):
                    package.platform_listings.append(result)

        await store.set_listing(package)
        return package

