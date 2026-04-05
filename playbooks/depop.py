"""Depop playbook — research active prices + list items on Depop (clothing only)."""
from __future__ import annotations

from models.item_card import ItemCard, ItemCategory
from models.listing_package import ListingPackage
from playbooks.base import BasePlaybook


class DepopPlaybook(BasePlaybook):
    platform = "depop"
    CONDITION_MAP = {"Like New": "Like New", "Good": "Good", "Fair": "Fair"}

    def _is_clothing(self, item: ItemCard) -> bool:
        return item.category == ItemCategory.CLOTHING

    def research_task(self, item: ItemCard) -> tuple[str, list[dict]]:
        task = """
Look at the first 10-15 active listings on this page. Extract ALL visible prices as a list.
Also note the total number of listings found if shown.

Return as JSON: {"sold_prices": [N, N, N, ...], "listings_found": N}
"""
        url = self._build_search_url("https://depop.com/search/?q={query}", item)
        return (task.strip(), [{"navigate": {"url": url}}])

    def listing_task(self, item: ItemCard, package: ListingPackage) -> tuple[str, list[dict]]:
        images = self._select_images(package, count=4)
        images_str = self._format_image_paths(images)
        condition = self._map_condition(item.condition_label)

        task = f"""
1. For Photos: upload photos in this order (first becomes the cover photo):
{images_str}
   Wait for all photos to finish uploading. Slots are labeled (Cover, Front, Back, etc.).

2. For Description: paste this text exactly:
{package.description}

3. For Price: enter {package.price_strategy:.2f}

4. For Category: select from the dropdown the most relevant category for '{item.name_guess}'.

5. For Brand: select from the dropdown or type the manufacturer/brand name.
   If unclear, enter the first word of the item name.

6. For Condition: select '{condition}' from the condition dropdown.

7. Click 'Continue' to publish the listing.
   Return the listing URL from the confirmation page.
"""
        return (task.strip(), [{"navigate": {"url": "https://depop.com/products/create"}}])

    def parse_research(self, result: str) -> dict:
        return self._parse_price_list_research(result, price_type="active")
