"""eBay playbook — research sold prices + list items on eBay."""
from __future__ import annotations

from extraction import make_initial_actions
from models.item_card import ItemCard
from models.listing_package import ListingPackage
from playbooks.base import BasePlaybook


class EbayPlaybook(BasePlaybook):
    platform = "ebay"

    def research_task(self, item: ItemCard) -> tuple[str, list[dict]]:
        task = """
The page may have already run a JavaScript extraction. Check if there is a JSON result
with prices, avg, and count visible in the page or console output.

If extraction results are available, return them directly as:
{"sold_prices": [N, N, ...], "listings_found": N}

Otherwise, look at the first 10-15 sold listings on this page. Extract ALL visible sale prices as a list.
Also note the total number of results shown.

Return as JSON: {"sold_prices": [N, N, N, ...], "listings_found": N}
"""
        url = self._build_search_url(
            "https://ebay.com/sch/i.html?_nkw={query}&LH_Complete=1&LH_Sold=1", item
        )
        return (task.strip(), make_initial_actions("ebay", url))

    def listing_task(self, item: ItemCard, package: ListingPackage) -> tuple[str, list[dict]]:
        title = self._truncate_title(package.title)
        images = self._select_images(package, count=6)
        images_str = self._format_image_paths(images)

        # Build condition description for LLM to match against eBay's tiles
        if item.has_defects:
            defects = "; ".join(d.description for d in item.all_defects[:3])
            condition_desc = f"The item is in '{item.condition_label}' condition with these issues: {defects}."
        else:
            condition_desc = f"The item is in '{item.condition_label}' condition with no visible defects."

        task = f"""
You are on eBay's sell page. Follow these steps:

1. Click 'List an item'. If a product library search box appears, type '{item.name_guess}'
   and either select the best match or click 'Continue without match' / 'Skip'.

2. In the Title field, type exactly: {title}

3. For Category: type '{item.name_guess}' in the category search box, select the most
   relevant result from the dropdown.

4. For Condition: select the option that best matches this description:
   {condition_desc}

5. For Photos: click the photo upload area. Upload these files in order:
{images_str}
   Wait for ALL photos to finish uploading before continuing. You need at least 5 photos.

6. If you see 'Item Specifics' fields (Brand, Size, Color, Department, etc.),
   fill in what you can infer from the item name and description. Skip any you cannot determine.

7. For Price: enter {package.price_strategy:.2f} in the Buy It Now price field.

8. For Shipping: select 'Calculated shipping' so eBay computes cost from buyer location.

9. For Description: paste this text exactly:
{package.description}

10. Click 'List it' or 'Continue' (whichever button is shown) to publish.
    Wait for the confirmation page with the listing URL.
    Return the listing URL from the confirmation page.
"""
        return (task.strip(), [{"navigate": {"url": "https://ebay.com/sell"}}])

    def parse_research(self, result: str) -> dict:
        return self._parse_price_list_research(result, price_type="sold")
