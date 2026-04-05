"""Amazon playbook — research-only. Finds replacement parts and repair costs."""
from __future__ import annotations

from urllib.parse import quote_plus

from models.item_card import ItemCard
from models.listing_package import ListingPackage
from playbooks.base import BasePlaybook


class AmazonPlaybook(BasePlaybook):
    platform = "amazon"

    def research_task(self, item: ItemCard) -> tuple[str, list[dict]]:
        query = f"{item.name_guess} replacement parts"
        defect_summary = ", ".join(d.description for d in item.all_defects[:3])
        if defect_summary:
            query += f" {defect_summary}"

        task = """
Look at the first 5-10 results on this page. For each relevant result extract:
- Part name
- Price
- Product URL

Return as JSON: {"parts": [{"part_name": "...", "part_price": N, "part_url": "..."}]}
"""
        url = f"https://amazon.com/s?k={quote_plus(query)}"
        return (task.strip(), [{"navigate": {"url": url}}])

    def listing_task(self, item: ItemCard, package: ListingPackage) -> tuple[str, list[dict]]:
        task = "This is a research-only platform. Return 'SKIPPED: research-only platform' immediately."
        return (task, [])

    def parse_research(self, result: str) -> dict:
        data = self._safe_parse_json(result)
        if data is None:
            return self._make_research_result(0.0, 0, error="invalid json")
        parts = data.get("parts", [])
        total = sum(float(p.get("part_price", 0)) for p in parts)
        return self._make_research_result(
            avg_sold_price=0.0,
            listings_found=0,
            parts=parts,
            total_repair_cost=total,
        )
