from __future__ import annotations

import enum

from pydantic import BaseModel, Field


class ListingImage(BaseModel):
    path: str
    role: str  # "hero" | "secondary" | "defect_proof" | "spec_card"
    original_path: str = ""
    optimized: bool = False


class PlatformStatus(str, enum.Enum):
    PREPARING = "preparing"
    DRAFTING = "drafting"
    PUBLISHING = "publishing"
    LIVE = "live"
    FAILED = "failed"
    SKIPPED = "skipped"
    ARCHIVED = "archived"


class PlatformListing(BaseModel):
    platform: str
    status: PlatformStatus = PlatformStatus.PREPARING
    platform_listing_id: str = ""
    platform_offer_id: str = ""
    url: str = ""
    error: str = ""


class ListingPackage(BaseModel):
    item_id: str
    job_id: str = ""
    title: str = ""
    description: str = ""
    specs: dict[str, str] = Field(default_factory=dict)
    condition_summary: str = ""
    defects_disclosure: str = ""
    price_strategy: float = 0.0
    price_min: float = 0.0
    price_max: float = 0.0
    images: list[ListingImage] = Field(default_factory=list)
    platform_listings: list[PlatformListing] = Field(default_factory=list)
    category_id: str = ""
    shipping_policy: str = "standard"

    # v2 additions for orchestrator pipeline
    platforms: list[str] = Field(default_factory=list)
    prices: dict[str, float] = Field(default_factory=dict)
    research: dict[str, dict] = Field(default_factory=dict)

    @property
    def hero_image(self) -> ListingImage | None:
        for img in self.images:
            if img.role == "hero":
                return img
        return self.images[0] if self.images else None

    @property
    def is_live_anywhere(self) -> bool:
        return any(pl.status == PlatformStatus.LIVE for pl in self.platform_listings)
