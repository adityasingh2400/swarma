"""Facebook Marketplace playbook — research active prices + list items."""
from __future__ import annotations

from extraction import make_initial_actions
from models.item_card import ItemCard
from models.listing_package import ListingPackage
from playbooks.base import BasePlaybook


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

        task = f"""
If you see a 'Marketplace Terms' or 'Get started' dialog, accept/dismiss it first.

1. For Photos: click the photo upload area. Upload these files in order:
{images_str}
   The first photo becomes the listing thumbnail. Wait for uploads to complete.

2. For Title: type exactly: {title}

3. For Price: enter {price}

4. For Category: select the most relevant category for '{item.name_guess}'.

5. For Condition: select '{condition}'.

6. For Description: paste this text exactly:
{package.description}

Location auto-fills from your profile. No shipping needed for local listings.

7. To advance through 'Next' and 'Publish' buttons:
   IMPORTANT — Facebook's dynamic DOM often invalidates element indices after page transitions.
   If clicking a 'Next' or 'Publish' button fails or the index is unavailable, immediately
   use JavaScript instead:
   evaluate: document.querySelectorAll('div[role="button"]').forEach(b => {{ if(b.innerText.trim() === 'Next' || b.innerText.trim() === 'Publish') b.click() }})

   Click 'Next' through each step until you reach 'Publish'. Click 'Publish' to post.

8. After publishing, you should be redirected to the Selling dashboard.
   Return the listing URL. If you see 'Boost your listing', close the dialog first.

CRITICAL: Do not spend more than 2 attempts on any single button click. Use JS evaluate as fallback.
"""
        return (task.strip(), [{"navigate": {"url": "https://facebook.com/marketplace/create/item"}}])

    def parse_research(self, result: str) -> dict:
        return self._parse_price_list_research(result, price_type="active")
