"""Base playbook with shared helpers. All platform playbooks extend this."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus

logger = logging.getLogger("swarmsell.playbooks")

from contracts import Playbook
from models.item_card import ItemCard
from models.listing_package import ListingPackage


class BasePlaybook(Playbook):
    platform: str = ""

    # Override per-platform if needed. Maps ItemCard.condition_label -> platform label.
    CONDITION_MAP: dict[str, str] = {}

    # --- Shared helpers ---

    def _truncate_title(self, title: str, max_len: int = 80) -> str:
        """Truncate title at word boundary."""
        if len(title) <= max_len:
            return title
        return title[:max_len].rsplit(" ", 1)[0]

    def _select_images(self, package: ListingPackage, count: int = 6) -> list[str]:
        """Pick the most differentiated photos from ~10 available.

        Strategy: hero first, then one per unique role (defect_proof, spec_card),
        then fill remaining from secondary/unused images.
        """
        if not package.images:
            return []

        selected: list[str] = []
        used_indices: set[int] = set()

        # 1. Hero first
        for i, img in enumerate(package.images):
            if img.role == "hero":
                selected.append(img.path)
                used_indices.add(i)
                break

        # 2. One of each differentiated role
        for role in ("defect_proof", "spec_card"):
            if len(selected) >= count:
                break
            for i, img in enumerate(package.images):
                if i not in used_indices and img.role == role:
                    selected.append(img.path)
                    used_indices.add(i)
                    break

        # 3. Fill remaining from unused images
        for i, img in enumerate(package.images):
            if len(selected) >= count:
                break
            if i not in used_indices:
                selected.append(img.path)
                used_indices.add(i)

        return selected[:count]

    def _format_image_paths(self, paths: list[str]) -> str:
        """Format image paths for agent consumption. One per line."""
        return "\n".join(paths)

    def _map_condition(self, label: str) -> str:
        """Map ItemCard.condition_label to platform-specific condition string."""
        return self.CONDITION_MAP.get(label, label)

    def _build_search_url(self, base: str, item: ItemCard) -> str:
        """Build a search URL with encoded item name."""
        return base.format(query=quote_plus(item.name_guess))

    def _safe_parse_json(self, result: str) -> dict | None:
        """Extract JSON from agent output. Handles:
        1. Clean JSON string
        2. Escaped-quote JSON (e.g. {\"key\": \"val\"} from some LLM outputs)
        3. JSON wrapped in markdown fences
        4. JSON embedded in prose
        Returns None if no JSON found."""
        if result is None:
            return None

        candidates = [result]
        # Handle escaped-quote output from some agents (live test finding):
        # agents return {\"key\": \"val\"} with literal backslash-quote pairs.
        if r'\"' in result:
            candidates.append(result.replace(r'\"', '"'))

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.debug("Direct JSON parse failed, trying next strategy: %s", exc)

        for candidate in candidates:
            fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
            if fence_match:
                try:
                    return json.loads(fence_match.group(1))
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.debug("Fenced JSON parse failed: %s", exc)

        for candidate in candidates:
            brace_match = re.search(r"\{.*\}", candidate, re.DOTALL)
            if brace_match:
                try:
                    return json.loads(brace_match.group(0))
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.debug("Brace-extracted JSON parse failed: %s", exc)

        return None

    def _make_research_result(
        self,
        avg_sold_price: float,
        listings_found: int,
        price_type: str = "sold",
        **extra,
    ) -> dict:
        """Build a well-formed route_decision input dict."""
        result = {
            "avg_sold_price": avg_sold_price,
            "listings_found": listings_found,
            "price_type": price_type,
        }
        result.update(extra)
        return result

    def _parse_price_list_research(self, result: str, price_type: str = "sold") -> dict:
        """Shared parse_research for platforms returning price lists.
        Handles both our agent format and Person 1's JS extractor format."""
        if result is None:
            return self._make_research_result(0.0, 0, price_type=price_type)
        data = self._safe_parse_json(result)
        if data is None:
            return self._make_research_result(0.0, 0, price_type=price_type, error="invalid json")
        # Handle both key formats, filter non-numeric values (agents sometimes return "339.99 to 409.99")
        raw_prices = data.get("sold_prices") if "sold_prices" in data else data.get("prices", [])
        prices = []
        for p in raw_prices:
            if isinstance(p, (int, float)):
                prices.append(float(p))
            elif isinstance(p, str):
                # Try to extract first number from strings like "339.99 to 409.99"
                import re
                match = re.search(r"[\d.]+", p)
                if match:
                    try:
                        prices.append(float(match.group()))
                    except ValueError:
                        pass
        raw_count = data.get("listings_found") if "listings_found" in data else data.get("count")
        if raw_count is None:
            count = len(prices)
        elif isinstance(raw_count, str):
            # Handle strings like "9.74K", "1,200", etc.
            cleaned = raw_count.lower().replace(",", "").strip()
            if cleaned.endswith("k"):
                count = int(float(cleaned[:-1]) * 1000)
            elif cleaned.endswith("m"):
                count = int(float(cleaned[:-1]) * 1000000)
            else:
                try:
                    count = int(float(cleaned))
                except ValueError:
                    count = len(prices)
        else:
            count = int(raw_count)
        avg = data["avg"] if "avg" in data else (sum(prices) / len(prices) if prices else 0.0)
        return self._make_research_result(
            avg_sold_price=avg, listings_found=count, price_type=price_type
        )
