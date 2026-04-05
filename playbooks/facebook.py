"""Facebook Marketplace playbook — research active prices + list items."""
from __future__ import annotations

from models.item_card import ItemCard
from models.listing_package import ListingPackage
from playbooks.base import BasePlaybook


class FacebookPlaybook(BasePlaybook):
    platform = "facebook"
    CONDITION_MAP = {"Like New": "Like New", "Good": "Good", "Fair": "Fair"}

    def research_task(self, item: ItemCard) -> tuple[str, list[dict]]:
        task = """
Look at the first 10-15 active listings on this page. Extract ALL visible prices as a list.
Also note the total number of listings found if shown.

Return as JSON: {"sold_prices": [N, N, N, ...], "listings_found": N}
"""
        url = self._build_search_url(
            "https://facebook.com/marketplace/search?query={query}", item
        )
        return (task.strip(), [{"navigate": {"url": url}}])

    def listing_task(self, item: ItemCard, package: ListingPackage) -> tuple[str, list[dict]]:
        title = self._truncate_title(package.title)
        images = self._select_images(package, count=6)
        images_str = self._format_image_paths(images)
        condition = self._map_condition(item.condition_label)

        task = f"""
If you see a 'Marketplace Terms' or 'Get started' dialog, accept/dismiss it first.

1. For Title: type exactly: {title}

2. For Price: enter {package.price_strategy:.2f}

3. For Category: select the most relevant category for '{item.name_guess}'.

4. For Condition: select '{condition}'.

5. For Photos: click the photo upload area. Upload these files in order:
{images_str}
   The first photo becomes the listing thumbnail.

6. For Description: paste this text exactly:
{package.description}

Location auto-fills from your profile. No shipping needed for local listings.

7. Click 'Next' and then 'Publish' to post the listing.
   Return the listing URL from the confirmation page.
"""
        return (task.strip(), [{"navigate": {"url": "https://facebook.com/marketplace/create/item"}}])

    def parse_research(self, result: str) -> dict:
        return self._parse_price_list_research(result, price_type="active")
