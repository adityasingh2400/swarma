from __future__ import annotations

import logging

from backend.adapters.base import PlatformAdapter
from backend.models.listing_package import ListingPackage, PlatformListing, PlatformStatus
from backend.services.ebay_api import EbayService

logger = logging.getLogger(__name__)


class EbayAdapter(PlatformAdapter):
    platform_name = "ebay"

    def __init__(self, service: EbayService | None = None) -> None:
        self.service = service or EbayService()

    async def create_draft(self, package: ListingPackage) -> PlatformListing:
        pl = PlatformListing(platform=self.platform_name, status=PlatformStatus.DRAFTING)

        try:
            result = await self.service.create_listing(package)
            pl.platform_listing_id = result.get("sku", "")
            pl.platform_offer_id = result.get("offerId", "")
            pl.status = PlatformStatus.PUBLISHING
            logger.info(
                "eBay draft created: sku=%s offer=%s",
                pl.platform_listing_id,
                pl.platform_offer_id,
            )
        except Exception:
            logger.exception("eBay draft creation failed for item=%s", package.item_id)
            pl.status = PlatformStatus.FAILED
            pl.error = "Draft creation failed"

        return pl

    async def publish(self, listing: PlatformListing) -> PlatformListing:
        if listing.status == PlatformStatus.FAILED:
            return listing

        if not listing.platform_offer_id:
            listing.status = PlatformStatus.FAILED
            listing.error = "No offer ID to publish"
            return listing

        try:
            result = await self.service.publish_listing(listing.platform_offer_id)
            listing.platform_listing_id = result.get("listingId", listing.platform_listing_id)
            listing.status = PlatformStatus.LIVE
            listing.url = f"https://www.ebay.com/itm/{listing.platform_listing_id}"
            logger.info("eBay listing live: %s", listing.platform_listing_id)
        except Exception:
            logger.exception("eBay publish failed for offer=%s", listing.platform_offer_id)
            listing.status = PlatformStatus.FAILED
            listing.error = "Publish failed"

        return listing

    async def archive(self, listing_id: str) -> bool:
        logger.info("eBay archive requested for listing=%s", listing_id)
        return True

    async def get_messages(self, listing_id: str) -> list[dict]:
        logger.info("eBay message fetch for listing=%s", listing_id)
        return []
