from __future__ import annotations

import logging

from backend.adapters.base import PlatformAdapter
from backend.config import settings
from backend.models.listing_package import ListingPackage, PlatformListing, PlatformStatus

logger = logging.getLogger(__name__)


class DepopAdapter(PlatformAdapter):
    platform_name = "depop"

    async def create_draft(self, package: ListingPackage) -> PlatformListing:
        if not settings.enable_depop_adapter:
            logger.info("Depop adapter is experimental and currently disabled")
            return PlatformListing(
                platform=self.platform_name,
                status=PlatformStatus.SKIPPED,
                error="Depop adapter is experimental — enable via settings.enable_depop_adapter",
            )

        logger.info("Depop adapter is experimental — draft creation stub for item=%s", package.item_id)
        return PlatformListing(
            platform=self.platform_name,
            status=PlatformStatus.DRAFTING,
            error="Depop integration pending",
        )

    async def publish(self, listing: PlatformListing) -> PlatformListing:
        if not settings.enable_depop_adapter:
            logger.info("Depop adapter is experimental and currently disabled")
            listing.status = PlatformStatus.SKIPPED
            return listing

        logger.info("Depop adapter is experimental — publish stub for listing=%s", listing.platform_listing_id)
        listing.status = PlatformStatus.SKIPPED
        listing.error = "Depop publish not yet implemented"
        return listing

    async def archive(self, listing_id: str) -> bool:
        logger.info("Depop adapter is experimental — archive stub for %s", listing_id)
        return False

    async def get_messages(self, listing_id: str) -> list[dict]:
        logger.info("Depop adapter is experimental — messages stub for %s", listing_id)
        return []
