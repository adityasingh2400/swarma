from __future__ import annotations

import logging
import uuid

import httpx

from backend.config import settings
from backend.models.route_bid import ComparableListing
from backend.models.listing_package import ListingPackage, PlatformListing, PlatformStatus

logger = logging.getLogger(__name__)


class EbayService:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=10.0)
        return self._http

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.ebay_oauth_token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Content-Type": "application/json",
        }

    async def search_comps(
        self,
        query: str,
        category: str | None = None,
    ) -> list[ComparableListing]:
        if settings.demo_mode and not settings.ebay_oauth_token:
            return self._mock_comps(query)

        try:
            client = await self._client()
            params: dict[str, str | int] = {"q": query, "limit": 10}
            if category:
                params["category_ids"] = category

            resp = await client.get(
                f"{settings.ebay_browse_url}/item_summary/search",
                params=params,
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            results: list[ComparableListing] = []
            for summary in data.get("itemSummaries", []):
                price_val = 0.0
                if price := summary.get("price"):
                    price_val = float(price.get("value", 0))

                image_url = ""
                if thumb := summary.get("thumbnailImages"):
                    image_url = thumb[0].get("imageUrl", "")

                results.append(ComparableListing(
                    platform="ebay",
                    title=summary.get("title", ""),
                    price=price_val,
                    shipping=summary.get("shippingOptions", [{}])[0].get("shippingCostType", ""),
                    condition=summary.get("condition", ""),
                    image_url=image_url,
                    url=summary.get("itemWebUrl", ""),
                    match_score=0.8,
                ))
            return results

        except Exception:
            logger.exception("eBay comp search failed for query=%s", query)
            if settings.demo_mode:
                return self._mock_comps(query)
            return []

    async def create_listing(self, package: ListingPackage) -> dict:
        if settings.demo_mode and not settings.ebay_oauth_token:
            return self._mock_create_listing(package)

        try:
            client = await self._client()
            headers = self._auth_headers()
            sku = f"RR-{package.item_id}-{uuid.uuid4().hex[:6]}"

            image_urls = [img.path for img in package.images[:12] if img.path.startswith("http")]
            if not image_urls:
                image_urls = ["https://via.placeholder.com/500x500.jpg?text=No+Photo"]

            inventory_body = {
                "availability": {
                    "shipToLocationAvailability": {"quantity": 1}
                },
                "condition": self._map_condition(package.condition_summary),
                "product": {
                    "title": package.title[:80],
                    "description": package.description[:4000] or package.title,
                    "imageUrls": image_urls,
                },
            }
            logger.info("eBay inventory PUT for sku=%s: %s", sku, inventory_body)
            resp = await client.put(
                f"{settings.ebay_sell_url}/inventory_item/{sku}",
                json=inventory_body,
                headers=headers,
            )
            if resp.status_code >= 400:
                logger.error("eBay inventory_item error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()

            offer_body = {
                "sku": sku,
                "marketplaceId": "EBAY_US",
                "format": "FIXED_PRICE",
                "pricingSummary": {
                    "price": {"value": str(round(package.price_strategy, 2)), "currency": "USD"}
                },
                "listingDescription": package.description[:4000] or package.title,
                "categoryId": package.category_id or "9355",
            }
            resp = await client.post(
                f"{settings.ebay_sell_url}/offer",
                json=offer_body,
                headers=headers,
            )
            if resp.status_code >= 400:
                logger.error("eBay offer error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            offer_data = resp.json()
            offer_id = offer_data.get("offerId", "")

            return {"sku": sku, "offerId": offer_id, "listingId": ""}

        except Exception:
            logger.exception("eBay create listing failed for item=%s", package.item_id)
            if settings.demo_mode:
                return self._mock_create_listing(package)
            raise

    async def publish_listing(self, offer_id: str) -> dict:
        if settings.demo_mode and not settings.ebay_oauth_token:
            return {"listingId": f"demo-listing-{uuid.uuid4().hex[:8]}", "status": "LIVE"}

        try:
            client = await self._client()
            resp = await client.post(
                f"{settings.ebay_sell_url}/offer/{offer_id}/publish",
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return {"listingId": data.get("listingId", ""), "status": "LIVE"}

        except Exception:
            logger.exception("eBay publish failed for offer=%s", offer_id)
            if settings.demo_mode:
                return {"listingId": f"demo-listing-{uuid.uuid4().hex[:8]}", "status": "LIVE"}
            raise

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    @staticmethod
    def _map_condition(condition_label: str) -> str:
        mapping = {
            "New": "NEW",
            "Like New": "LIKE_NEW",
            "Excellent": "USED_EXCELLENT",
            "Very Good": "USED_VERY_GOOD",
            "Good": "USED_GOOD",
            "Fair": "USED_ACCEPTABLE",
            "Poor": "FOR_PARTS_OR_NOT_WORKING",
        }
        return mapping.get(condition_label, "USED_GOOD")

    @staticmethod
    def _mock_comps(query: str) -> list[ComparableListing]:
        return [
            ComparableListing(
                platform="ebay",
                title=f"{query} - Great Condition",
                price=89.99,
                shipping="FREE",
                condition="Good",
                image_url="https://via.placeholder.com/150",
                url="https://ebay.com/itm/demo1",
                match_score=0.90,
            ),
            ComparableListing(
                platform="ebay",
                title=f"{query} - Used",
                price=72.50,
                shipping="$5.99",
                condition="Good",
                image_url="https://via.placeholder.com/150",
                url="https://ebay.com/itm/demo2",
                match_score=0.85,
            ),
            ComparableListing(
                platform="ebay",
                title=f"{query} - For Parts",
                price=45.00,
                shipping="$8.99",
                condition="Fair",
                image_url="https://via.placeholder.com/150",
                url="https://ebay.com/itm/demo3",
                match_score=0.70,
            ),
        ]

    @staticmethod
    def _mock_create_listing(package: ListingPackage) -> dict:
        return {
            "sku": f"RR-{package.item_id}-demo",
            "offerId": f"demo-offer-{uuid.uuid4().hex[:8]}",
            "listingId": "",
        }
