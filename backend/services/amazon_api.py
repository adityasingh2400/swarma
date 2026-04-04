from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from backend.config import settings
from backend.models.route_bid import RepairCandidate

logger = logging.getLogger(__name__)

PAAPI_ENDPOINT = "https://webservices.amazon.com/paapi5/searchitems"
PAAPI_SERVICE = "ProductAdvertisingAPI"
PAAPI_REGION = "us-east-1"


class AmazonService:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def search_parts(
        self,
        query: str,
        category: str = "All",
    ) -> list[RepairCandidate]:
        if not settings.amazon_access_key or settings.demo_mode:
            return self._mock_parts(query)

        try:
            client = await self._client()
            payload = {
                "Keywords": query,
                "SearchIndex": category,
                "ItemCount": 5,
                "Resources": [
                    "ItemInfo.Title",
                    "Offers.Listings.Price",
                    "Images.Primary.Large",
                ],
                "PartnerTag": settings.amazon_partner_tag,
                "PartnerType": "Associates",
                "Marketplace": "www.amazon.com",
            }

            now = datetime.now(timezone.utc)
            headers = self._sign_request(payload, now)
            resp = await client.post(PAAPI_ENDPOINT, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            results: list[RepairCandidate] = []
            for item in data.get("SearchResult", {}).get("Items", []):
                title = item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", "")
                price = 0.0
                listings = item.get("Offers", {}).get("Listings", [])
                if listings:
                    price = float(listings[0].get("Price", {}).get("Amount", 0))

                image_url = ""
                primary = item.get("Images", {}).get("Primary", {})
                if large := primary.get("Large"):
                    image_url = large.get("URL", "")

                results.append(RepairCandidate(
                    part_name=title,
                    part_query=query,
                    part_price=price,
                    part_url=item.get("DetailPageURL", ""),
                    part_image_url=image_url,
                    source="amazon",
                ))
            return results

        except Exception:
            logger.exception("Amazon PA-API search failed for query=%s", query)
            if settings.demo_mode:
                return self._mock_parts(query)
            return []

    def _sign_request(self, payload: dict, now: datetime) -> dict[str, str]:
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        body = json.dumps(payload)

        canonical_headers = (
            f"content-type:application/json\n"
            f"host:webservices.amazon.com\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "content-type;host;x-amz-date"
        payload_hash = hashlib.sha256(body.encode()).hexdigest()

        canonical_request = (
            f"POST\n/paapi5/searchitems\n\n"
            f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )

        credential_scope = f"{date_stamp}/{PAAPI_REGION}/{PAAPI_SERVICE}/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        )

        def _sign(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode(), hashlib.sha256).digest()

        k_date = _sign(f"AWS4{settings.amazon_secret_key}".encode(), date_stamp)
        k_region = _sign(k_date, PAAPI_REGION)
        k_service = _sign(k_region, PAAPI_SERVICE)
        k_signing = _sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

        authorization = (
            f"AWS4-HMAC-SHA256 Credential={settings.amazon_access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        return {
            "Content-Type": "application/json",
            "Host": "webservices.amazon.com",
            "X-Amz-Date": amz_date,
            "Authorization": authorization,
        }

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    @staticmethod
    def _mock_parts(query: str) -> list[RepairCandidate]:
        return [
            RepairCandidate(
                part_name=f"Replacement Screen for {query}",
                part_query=query,
                part_price=29.99,
                part_url="https://amazon.com/dp/DEMO001",
                part_image_url="https://via.placeholder.com/150",
                source="amazon",
            ),
            RepairCandidate(
                part_name=f"Battery Replacement Kit for {query}",
                part_query=query,
                part_price=18.50,
                part_url="https://amazon.com/dp/DEMO002",
                part_image_url="https://via.placeholder.com/150",
                source="amazon",
            ),
            RepairCandidate(
                part_name=f"Repair Tool Set - Compatible with {query}",
                part_query=query,
                part_price=12.99,
                part_url="https://amazon.com/dp/DEMO003",
                part_image_url="https://via.placeholder.com/150",
                source="amazon",
            ),
        ]
