from __future__ import annotations

import csv
import io
import logging
import uuid
from pathlib import Path

from backend.adapters.base import PlatformAdapter
from backend.config import settings
from backend.models.listing_package import ListingPackage, PlatformListing, PlatformStatus

logger = logging.getLogger(__name__)


class MercariImportAdapter(PlatformAdapter):
    platform_name = "mercari"

    async def create_draft(self, package: ListingPackage) -> PlatformListing:
        pl = PlatformListing(platform=self.platform_name, status=PlatformStatus.DRAFTING)

        try:
            csv_path = self.generate_import_csv(package)
            pl.platform_listing_id = f"mercari-csv-{uuid.uuid4().hex[:8]}"
            pl.url = csv_path
            pl.status = PlatformStatus.PUBLISHING
            logger.info("Mercari CSV generated at %s", csv_path)
        except Exception:
            logger.exception("Mercari CSV generation failed for item=%s", package.item_id)
            pl.status = PlatformStatus.FAILED
            pl.error = "CSV generation failed"

        return pl

    async def publish(self, listing: PlatformListing) -> PlatformListing:
        if listing.status == PlatformStatus.FAILED:
            return listing

        listing.status = PlatformStatus.LIVE
        logger.info(
            "Mercari listing marked as ready for import: %s (CSV at %s)",
            listing.platform_listing_id,
            listing.url,
        )
        return listing

    async def archive(self, listing_id: str) -> bool:
        logger.info("Mercari archive requested for %s (manual action required)", listing_id)
        return True

    async def get_messages(self, listing_id: str) -> list[dict]:
        logger.info("Mercari messages not available via API for %s", listing_id)
        return []

    def generate_import_csv(self, package: ListingPackage) -> str:
        out_dir = Path(settings.optimized_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = str(out_dir / f"mercari_import_{package.item_id}.csv")

        condition_map = {
            "Like New": "Like new",
            "Good": "Good",
            "Fair": "Fair",
        }

        rows = [{
            "title": package.title[:100],
            "description": package.description[:1000],
            "price": f"{package.price_strategy:.2f}",
            "condition": condition_map.get(package.condition_summary, "Good"),
            "category": package.category_id or "Other",
            "shipping": package.shipping_policy,
            "photos": "|".join(img.path for img in package.images[:12]),
        }]

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

        Path(csv_path).write_text(buf.getvalue())
        return csv_path
