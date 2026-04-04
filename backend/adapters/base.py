from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models.listing_package import ListingPackage, PlatformListing


class PlatformAdapter(ABC):
    platform_name: str = ""

    @abstractmethod
    async def create_draft(self, package: ListingPackage) -> PlatformListing:
        ...

    @abstractmethod
    async def publish(self, listing: PlatformListing) -> PlatformListing:
        ...

    @abstractmethod
    async def archive(self, listing_id: str) -> bool:
        ...

    @abstractmethod
    async def get_messages(self, listing_id: str) -> list[dict]:
        ...
