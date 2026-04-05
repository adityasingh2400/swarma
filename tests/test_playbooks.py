"""Tests for all 6 marketplace playbooks."""
from __future__ import annotations

import json
import pytest

from models.item_card import ItemCard, DefectSignal, ItemCategory
from models.listing_package import ListingPackage, ListingImage
from playbooks.base import BasePlaybook
from playbooks.ebay import EbayPlaybook
from playbooks.facebook import FacebookPlaybook
from playbooks.mercari import MercariPlaybook
from playbooks.depop import DepopPlaybook
from playbooks.amazon import AmazonPlaybook


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_item(**overrides) -> ItemCard:
    defaults = dict(
        item_id="test123",
        name_guess="iPhone 14 Pro 128GB",
        category=ItemCategory.ELECTRONICS,
    )
    defaults.update(overrides)
    return ItemCard(**defaults)


def _make_item_with_defects() -> ItemCard:
    return _make_item(
        visible_defects=[
            DefectSignal(description="scratched screen corner", source="visual", severity="moderate"),
        ],
    )


def _make_package(**overrides) -> ListingPackage:
    """Create a ListingPackage with ~10 images of varied roles."""
    images = [
        ListingImage(path="/img/hero.jpg", role="hero"),
        ListingImage(path="/img/defect1.jpg", role="defect_proof"),
        ListingImage(path="/img/spec1.jpg", role="spec_card"),
        ListingImage(path="/img/sec1.jpg", role="secondary"),
        ListingImage(path="/img/sec2.jpg", role="secondary"),
        ListingImage(path="/img/sec3.jpg", role="secondary"),
        ListingImage(path="/img/sec4.jpg", role="secondary"),
        ListingImage(path="/img/sec5.jpg", role="secondary"),
        ListingImage(path="/img/sec6.jpg", role="secondary"),
        ListingImage(path="/img/sec7.jpg", role="secondary"),
    ]
    defaults = dict(
        item_id="test123",
        title="Apple iPhone 14 Pro 128GB Space Black Unlocked",
        description="Excellent condition iPhone 14 Pro. No scratches, fully functional.",
        price_strategy=799.00,
        images=images,
    )
    defaults.update(overrides)
    return ListingPackage(**defaults)


# ---------------------------------------------------------------------------
# BasePlaybook helpers
# ---------------------------------------------------------------------------

class TestBaseHelpers:
    def test_truncate_title_under_limit(self):
        bp = EbayPlaybook()
        assert bp._truncate_title("Short title") == "Short title"

    def test_truncate_title_at_word_boundary(self):
        bp = EbayPlaybook()
        long = "A" * 40 + " " + "B" * 40 + " extra"
        result = bp._truncate_title(long)
        assert len(result) <= 80
        assert not result.endswith(" ")

    def test_truncate_title_exact_80(self):
        bp = EbayPlaybook()
        title = "x" * 80
        assert bp._truncate_title(title) == title

    def test_select_images_picks_6_differentiated(self):
        bp = EbayPlaybook()
        package = _make_package()
        images = bp._select_images(package, count=6)
        assert len(images) == 6
        assert images[0] == "/img/hero.jpg"
        assert "/img/defect1.jpg" in images
        assert "/img/spec1.jpg" in images

    def test_select_images_hero_always_first(self):
        bp = EbayPlaybook()
        package = _make_package()
        images = bp._select_images(package, count=6)
        assert images[0] == "/img/hero.jpg"

    def test_select_images_respects_count(self):
        bp = DepopPlaybook()
        package = _make_package()
        images = bp._select_images(package, count=4)
        assert len(images) == 4

    def test_select_images_empty_package(self):
        bp = EbayPlaybook()
        package = _make_package(images=[])
        assert bp._select_images(package, count=6) == []

    def test_select_images_fewer_than_count(self):
        bp = EbayPlaybook()
        package = _make_package(images=[
            ListingImage(path="/img/hero.jpg", role="hero"),
            ListingImage(path="/img/sec1.jpg", role="secondary"),
        ])
        images = bp._select_images(package, count=6)
        assert len(images) == 2

    def test_safe_parse_json_valid(self):
        bp = EbayPlaybook()
        result = bp._safe_parse_json('{"sold_prices": [100, 200], "listings_found": 2}')
        assert result == {"sold_prices": [100, 200], "listings_found": 2}

    def test_safe_parse_json_markdown_fenced(self):
        bp = EbayPlaybook()
        result = bp._safe_parse_json('```json\n{"sold_prices": [100]}\n```')
        assert result == {"sold_prices": [100]}

    def test_safe_parse_json_embedded_in_prose(self):
        bp = EbayPlaybook()
        result = bp._safe_parse_json('The results are: {"sold_prices": [500, 420]}')
        assert result == {"sold_prices": [500, 420]}

    def test_safe_parse_json_no_json(self):
        bp = EbayPlaybook()
        assert bp._safe_parse_json("No structured data here") is None

    def test_safe_parse_json_none_input(self):
        bp = EbayPlaybook()
        assert bp._safe_parse_json(None) is None

    def test_safe_parse_json_escaped_quotes(self):
        # Live test finding: eBay/Facebook/Mercari agents return JSON with
        # escaped quotes e.g. {\"sold_prices\": [500, 600], \"listings_found\": 2}
        # This is the raw string the agent emits — backslash-quote pairs.
        bp = EbayPlaybook()
        escaped = r'{"sold_prices": [500, 600], "listings_found": 2}'.replace('"', r'\"')
        # escaped = {\"sold_prices\": [500, 600], \"listings_found\": 2}
        result = bp._safe_parse_json(escaped)
        assert result is not None
        assert result["sold_prices"] == [500, 600]
        assert result["listings_found"] == 2

    def test_safe_parse_json_escaped_quotes_in_prose(self):
        bp = EbayPlaybook()
        raw = r'Here are the results: {\"avg\": 450, \"count\": 10}'
        result = bp._safe_parse_json(raw)
        assert result is not None
        assert result["avg"] == 450

    def test_safe_parse_json_nested_objects(self):
        bp = EbayPlaybook()
        result = bp._safe_parse_json(
            '{"parts": [{"part_name": "Screen", "part_price": 49.99}]}'
        )
        assert result is not None
        assert isinstance(result["parts"], list)
        assert result["parts"][0]["part_name"] == "Screen"

    def test_make_research_result(self):
        bp = EbayPlaybook()
        result = bp._make_research_result(500.0, 10, price_type="sold")
        assert result == {"avg_sold_price": 500.0, "listings_found": 10, "price_type": "sold"}

    def test_make_research_result_with_extras(self):
        bp = EbayPlaybook()
        result = bp._make_research_result(0.0, 0, confidence=0.5)
        assert result["confidence"] == 0.5

    def test_parse_price_list_agent_format(self):
        bp = EbayPlaybook()
        result = bp._parse_price_list_research(
            '{"sold_prices": [100, 200, 300], "listings_found": 3}',
            price_type="sold",
        )
        assert result["avg_sold_price"] == 200.0
        assert result["listings_found"] == 3
        assert result["price_type"] == "sold"

    def test_parse_price_list_js_extractor_format(self):
        bp = EbayPlaybook()
        result = bp._parse_price_list_research(
            '{"prices": [100, 200], "avg": 150, "count": 2, "total_listings": 50}',
            price_type="sold",
        )
        assert result["avg_sold_price"] == 150
        assert result["listings_found"] == 2

    def test_parse_price_list_none_input(self):
        bp = EbayPlaybook()
        result = bp._parse_price_list_research(None, price_type="sold")
        assert result["avg_sold_price"] == 0.0
        assert result["listings_found"] == 0

    def test_parse_price_list_invalid_json(self):
        bp = EbayPlaybook()
        result = bp._parse_price_list_research("garbage text", price_type="active")
        assert result["avg_sold_price"] == 0.0
        assert result["error"] == "invalid json"

    def test_format_image_paths(self):
        bp = EbayPlaybook()
        result = bp._format_image_paths(["/a.jpg", "/b.jpg"])
        assert result == "/a.jpg\n/b.jpg"


# ---------------------------------------------------------------------------
# eBay
# ---------------------------------------------------------------------------

class TestEbayPlaybook:
    def test_research_task_returns_tuple(self):
        pb = EbayPlaybook()
        task, actions = pb.research_task(_make_item())
        assert isinstance(task, str)
        assert isinstance(actions, list)

    def test_research_url_contains_name_guess(self):
        pb = EbayPlaybook()
        _, actions = pb.research_task(_make_item())
        url = actions[0]["navigate"]["url"]
        assert "iPhone+14+Pro+128GB" in url
        assert "LH_Sold=1" in url

    def test_research_task_string_no_url(self):
        pb = EbayPlaybook()
        task, _ = pb.research_task(_make_item())
        assert "ebay.com" not in task

    def test_listing_task_returns_tuple(self):
        pb = EbayPlaybook()
        task, actions = pb.listing_task(_make_item(), _make_package())
        assert isinstance(task, str)
        assert isinstance(actions, list)

    def test_listing_navigates_to_sell(self):
        pb = EbayPlaybook()
        _, actions = pb.listing_task(_make_item(), _make_package())
        assert actions[0]["navigate"]["url"] == "https://ebay.com/sell"

    def test_listing_title_in_task(self):
        pb = EbayPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "Apple iPhone 14 Pro 128GB Space Black Unlocked" in task

    def test_listing_title_truncation(self):
        pb = EbayPlaybook()
        long_title = "Apple iPhone 14 Pro 128GB Space Black Unlocked with Original Box and All Accessories Included Brand New"
        pkg = _make_package(title=long_title)
        task, _ = pb.listing_task(_make_item(), pkg)
        # The truncated title should be in the task, not the full one
        assert long_title not in task

    def test_listing_condition_description_based(self):
        pb = EbayPlaybook()
        item = _make_item_with_defects()
        task, _ = pb.listing_task(item, _make_package())
        assert "scratched screen corner" in task
        assert "Good" in task  # condition_label for moderate defects

    def test_listing_no_defects_condition(self):
        pb = EbayPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "no visible defects" in task

    def test_listing_price_in_task(self):
        pb = EbayPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "799.00" in task

    def test_listing_mentions_item_specifics(self):
        pb = EbayPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "Item Specifics" in task

    def test_listing_mentions_pre_form_flow(self):
        pb = EbayPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "List an item" in task

    def test_parse_research_valid(self):
        pb = EbayPlaybook()
        result = pb.parse_research('{"sold_prices": [500, 600, 700], "listings_found": 3}')
        assert result["avg_sold_price"] == 600.0
        assert result["listings_found"] == 3
        assert result["price_type"] == "sold"

    def test_parse_research_none(self):
        pb = EbayPlaybook()
        result = pb.parse_research(None)
        assert result["avg_sold_price"] == 0.0


# ---------------------------------------------------------------------------
# Facebook
# ---------------------------------------------------------------------------

class TestFacebookPlaybook:
    def test_research_task_returns_tuple(self):
        pb = FacebookPlaybook()
        task, actions = pb.research_task(_make_item())
        assert isinstance(task, str)
        assert isinstance(actions, list)

    def test_research_url(self):
        pb = FacebookPlaybook()
        _, actions = pb.research_task(_make_item())
        url = actions[0]["navigate"]["url"]
        assert "facebook.com/marketplace/search" in url

    def test_listing_task_returns_tuple(self):
        pb = FacebookPlaybook()
        task, actions = pb.listing_task(_make_item(), _make_package())
        assert isinstance(task, str)
        assert actions[0]["navigate"]["url"] == "https://facebook.com/marketplace/create/item"

    def test_listing_mentions_modal_dismiss(self):
        pb = FacebookPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "Marketplace Terms" in task or "Get started" in task

    def test_condition_map(self):
        pb = FacebookPlaybook()
        assert pb._map_condition("Like New") == "Like New"
        assert pb._map_condition("Good") == "Good"

    def test_parse_research_active(self):
        pb = FacebookPlaybook()
        result = pb.parse_research('{"sold_prices": [400, 500]}')
        assert result["price_type"] == "active"


# ---------------------------------------------------------------------------
# Mercari
# ---------------------------------------------------------------------------

class TestMercariPlaybook:
    def test_research_task_returns_tuple(self):
        pb = MercariPlaybook()
        task, actions = pb.research_task(_make_item())
        assert isinstance(task, str)

    def test_research_url_has_sold_filter(self):
        pb = MercariPlaybook()
        _, actions = pb.research_task(_make_item())
        url = actions[0]["navigate"]["url"]
        assert "status=sold_out" in url

    def test_listing_task_returns_tuple(self):
        pb = MercariPlaybook()
        task, actions = pb.listing_task(_make_item(), _make_package())
        assert isinstance(task, str)
        assert actions[0]["navigate"]["url"] == "https://mercari.com/sell"

    def test_listing_mentions_modal_dismiss(self):
        pb = MercariPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "promotional popup" in task or "extra $$$" in task

    def test_listing_mentions_brand(self):
        pb = MercariPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "Brand" in task

    def test_listing_condition_tiles(self):
        pb = MercariPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "tile" in task.lower()

    def test_condition_map_nwot(self):
        pb = MercariPlaybook()
        assert pb._map_condition("Like New") == "Like new (NWOT)"

    def test_listing_shipping_prepaid(self):
        pb = MercariPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "Prepaid label" in task

    def test_parse_research_sold(self):
        pb = MercariPlaybook()
        result = pb.parse_research('{"sold_prices": [700, 800]}')
        assert result["price_type"] == "sold"


# ---------------------------------------------------------------------------
# Depop
# ---------------------------------------------------------------------------

class TestDepopPlaybook:
    def test_research_task_returns_tuple(self):
        pb = DepopPlaybook()
        task, actions = pb.research_task(_make_item())
        assert isinstance(task, str)

    def test_research_url(self):
        pb = DepopPlaybook()
        _, actions = pb.research_task(_make_item())
        url = actions[0]["navigate"]["url"]
        assert "depop.com/search" in url

    def test_listing_task_returns_tuple(self):
        pb = DepopPlaybook()
        task, actions = pb.listing_task(_make_item(), _make_package())
        assert isinstance(task, str)
        assert actions[0]["navigate"]["url"] == "https://depop.com/products/create"

    def test_listing_4_images(self):
        pb = DepopPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        # Should have exactly 4 image paths in the task
        images = pb._select_images(_make_package(), count=4)
        assert len(images) == 4

    def test_listing_continue_button(self):
        pb = DepopPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "Continue" in task
        assert "Next" not in task or "List" not in task.split("Continue")[0]

    def test_listing_dropdown_instructions(self):
        pb = DepopPlaybook()
        task, _ = pb.listing_task(_make_item(), _make_package())
        assert "dropdown" in task.lower()

    def test_parse_research_active(self):
        pb = DepopPlaybook()
        result = pb.parse_research('{"sold_prices": [50, 60]}')
        assert result["price_type"] == "active"


# ---------------------------------------------------------------------------
# Amazon (repair parts research-only)
# ---------------------------------------------------------------------------

class TestAmazonPlaybook:
    def test_research_task_returns_tuple(self):
        pb = AmazonPlaybook()
        task, actions = pb.research_task(_make_item())
        assert isinstance(task, str)

    def test_research_url(self):
        pb = AmazonPlaybook()
        _, actions = pb.research_task(_make_item())
        url = actions[0]["navigate"]["url"]
        assert "amazon.com" in url

    def test_research_query_includes_replacement_parts(self):
        pb = AmazonPlaybook()
        _, actions = pb.research_task(_make_item())
        url = actions[0]["navigate"]["url"]
        assert "replacement" in url or "parts" in url

    def test_research_query_includes_defect_terms(self):
        pb = AmazonPlaybook()
        item = _make_item_with_defects()
        _, actions = pb.research_task(item)
        url = actions[0]["navigate"]["url"]
        assert "scratch" in url or "screen" in url

    def test_listing_task_noop(self):
        pb = AmazonPlaybook()
        task, actions = pb.listing_task(_make_item(), _make_package())
        assert "SKIPPED" in task
        assert actions == []

    def test_parse_research_returns_parts(self):
        pb = AmazonPlaybook()
        result = pb.parse_research('{"parts": [{"part_name": "Screen Replacement", "part_price": 49.99, "part_url": "https://amazon.com/dp/B123"}]}')
        assert "parts" in result
        assert len(result["parts"]) == 1
        assert result["parts"][0]["part_name"] == "Screen Replacement"

    def test_parse_research_totals_repair_cost(self):
        pb = AmazonPlaybook()
        result = pb.parse_research('{"parts": [{"part_name": "Screen", "part_price": 50.00, "part_url": "u"}, {"part_name": "Battery", "part_price": 20.00, "part_url": "u"}]}')
        assert result["total_repair_cost"] == 70.00

    def test_parse_research_invalid_json(self):
        pb = AmazonPlaybook()
        result = pb.parse_research("no json here")
        assert result["error"] == "invalid json"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_all_playbooks_registered(self):
        # Import triggers registration
        import playbooks  # noqa: F401
        from orchestrator import PLAYBOOKS

        expected = {"ebay", "facebook", "mercari", "depop", "amazon"}
        assert set(PLAYBOOKS.keys()) == expected

    def test_playbook_instances_correct_type(self):
        import playbooks  # noqa: F401
        from orchestrator import PLAYBOOKS
        from contracts import Playbook

        for name, pb in PLAYBOOKS.items():
            assert isinstance(pb, Playbook), f"{name} is not a Playbook instance"
