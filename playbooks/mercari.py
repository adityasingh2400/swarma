"""Mercari playbook — research sold prices + list items on Mercari."""
from __future__ import annotations

from extraction import make_initial_actions
from models.item_card import ItemCard
from models.listing_package import ListingPackage
from playbooks.base import BasePlaybook


class MercariPlaybook(BasePlaybook):
    platform = "mercari"
    CONDITION_MAP = {"Like New": "Like new (NWOT)", "Good": "Good", "Fair": "Fair"}

    def research_task(self, item: ItemCard) -> tuple[str, list[dict]]:
        task = """
The page may have already run a JavaScript extraction. Check if there is a JSON result
with prices, avg, and count visible in the page or console output.

If extraction results are available, return them directly as:
{"sold_prices": [N, N, ...], "listings_found": N}

Otherwise, look at the first 10-15 sold listings on this page. Extract ALL visible sold prices as a list.
Also note the total number of results shown if available.

Return as JSON: {"sold_prices": [N, N, N, ...], "listings_found": N}
"""
        url = self._build_search_url(
            "https://mercari.com/search/?keyword={query}&status=sold_out", item
        )
        return (task.strip(), make_initial_actions("mercari", url))

    def listing_task(self, item: ItemCard, package: ListingPackage) -> tuple[str, list[dict]]:
        title = self._truncate_title(package.title)
        images = self._select_images(package, count=6)
        images_str = self._format_image_paths(images)
        condition = self._map_condition(item.condition_label)
        price = int(round(package.price_strategy))

        task = f"""
If you see a promotional popup or 'Why not earn some extra $$$?' modal, close or dismiss it first.

1. For Photos: upload photos in this order (first becomes the thumbnail):
{images_str}
   Wait for all photos to finish uploading.

2. For Title: type exactly: {title}

3. For Category: click the category selector. Navigate the hierarchy to select
   the most relevant category for '{item.name_guess}'.

4. For Brand: enter the manufacturer or brand name you can identify from '{item.name_guess}'.
   If unclear, enter the first word of the item name.

5. For Condition: click the tile that says '{condition}'.
   The options are clickable tiles, not a dropdown.

6. For Price: enter {price}

7. For Shipping: accept the default 'Prepaid label' option.

8. For Description: paste this text exactly:
{package.description}

9. Click 'List' to publish.
   Return the listing URL from the confirmation page.

CRITICAL: Do not spend more than 2 attempts on any single field. If something won't change, move on.
"""
        return (task.strip(), [{"navigate": {"url": "https://mercari.com/sell"}}])

    def parse_research(self, result: str) -> dict:
        return self._parse_price_list_research(result, price_type="sold")
