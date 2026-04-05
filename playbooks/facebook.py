"""Facebook Marketplace playbook — research active prices + list items."""
from __future__ import annotations

from extraction import make_initial_actions
from models.item_card import ItemCard
from models.listing_package import ListingPackage
from playbooks.base import BasePlaybook


_CATEGORY_LABELS = {
    "electronics": "Electronics",
    "clothing": "Clothing & Accessories",
    "accessories": "Clothing & Accessories",
    "home": "Home & Garden",
    "sports": "Sporting Goods",
    "toys": "Toys & Games",
    "books": "Books, Movies & Music",
    "tools": "Tools & Hardware",
    "automotive": "Auto Parts & Accessories",
    "other": "Miscellaneous",
}


class FacebookPlaybook(BasePlaybook):
    platform = "facebook"
    CONDITION_MAP = {"Like New": "Like New", "Good": "Good", "Fair": "Fair"}

    def research_task(self, item: ItemCard) -> tuple[str, list[dict]]:
        task = """
The page may have already run a JavaScript extraction. Check if there is a JSON result
with prices, avg, and count visible in the page or console output.

If extraction results are available, return them directly as:
{"sold_prices": [N, N, ...], "listings_found": N}

Otherwise, look at the first 10-15 active listings on this page. Extract ALL visible prices as a list.
Also note the total number of listings found if shown.

Return as JSON: {"sold_prices": [N, N, N, ...], "listings_found": N}
"""
        url = self._build_search_url(
            "https://facebook.com/marketplace/search?query={query}", item
        )
        return (task.strip(), make_initial_actions("facebook", url))

    def listing_task(self, item: ItemCard, package: ListingPackage) -> tuple[str, list[dict]]:
        title = self._truncate_title(package.title)
        images = self._select_images(package, count=6)
        images_str = self._format_image_paths(images)
        condition = self._map_condition(item.condition_label)
        price = int(round(package.price_strategy))
        category_label = _CATEGORY_LABELS.get(item.category.value, "Miscellaneous")

        task = f"""If you see a 'Marketplace Terms' or 'Get started' dialog, accept/dismiss it first.

STEP 1 — PHOTOS: Upload these files using the file input (upload_file action on the file input element):
{images_str}
Wait briefly for uploads to finish.

STEP 2 — TITLE: Type exactly: {title}

STEP 3 — PRICE: Enter: {price}

STEP 4 — CATEGORY: Use this JavaScript to set category automatically:
evaluate: (function(){{ const inp = document.querySelector('input[aria-label="Category"]'); if(inp) {{ inp.focus(); inp.value = ""; const nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set; nativeSet.call(inp, "{category_label}"); inp.dispatchEvent(new Event("input", {{bubbles:true}})); inp.dispatchEvent(new Event("change", {{bubbles:true}})); }} return "typed {category_label}"; }})()
Then wait 2 seconds and click the first suggestion that appears in the dropdown.
If no dropdown appears, just proceed — category is optional on Facebook.

STEP 5 — CONDITION: Click the Condition dropdown and select '{condition}'.

STEP 6 — DESCRIPTION: Type this text:
{package.description}

STEP 7 — PUBLISH: Use JavaScript to click through Next/Publish:
evaluate: document.querySelectorAll('div[role="button"]').forEach(b => {{ const t = b.innerText.trim().toLowerCase(); if(t === 'next' || t === 'publish') b.click() }})
Run this JS 3 times with a 2-second wait between each to advance through all steps.

After publishing, return the listing URL or confirm success.
Do NOT spend more than 2 attempts on any single action. Use JS evaluate as fallback for any stuck button."""

        return (task.strip(), [{"navigate": {"url": "https://facebook.com/marketplace/create/item"}}])

    def parse_research(self, result: str) -> dict:
        return self._parse_price_list_research(result, price_type="active")
