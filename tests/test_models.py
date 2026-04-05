"""Tests for models/ — ItemCard, Job, ListingPackage, RouteBid."""
from __future__ import annotations

import pytest

from models.item_card import ItemCard, DefectSignal, ItemCategory
from models.job import Job, JobStatus
from models.listing_package import (
    ListingPackage, ListingImage, PlatformListing, PlatformStatus,
)
from models.route_bid import (
    RouteBid, RouteType, EffortLevel, SpeedEstimate,
    BestRouteDecision, ComparableListing, TradeInQuote, RepairCandidate,
)


# ── ItemCard ────────────────────────────────────────────────────────────────


class TestItemCard:
    def test_default_item_id_generated(self):
        card = ItemCard()
        assert len(card.item_id) == 10

    def test_unique_item_ids(self):
        ids = {ItemCard().item_id for _ in range(100)}
        assert len(ids) == 100

    def test_all_defects_combines_visible_and_spoken(self):
        card = ItemCard(
            visible_defects=[DefectSignal(description="scratch", source="visual")],
            spoken_defects=[DefectSignal(description="dent", source="spoken")],
        )
        assert len(card.all_defects) == 2

    def test_has_defects_true_when_defects_present(self):
        card = ItemCard(
            visible_defects=[DefectSignal(description="scratch", source="visual")],
        )
        assert card.has_defects is True

    def test_has_defects_false_when_no_defects(self):
        card = ItemCard()
        assert card.has_defects is False

    def test_is_electronics(self):
        card = ItemCard(category=ItemCategory.ELECTRONICS)
        assert card.is_electronics is True
        card2 = ItemCard(category=ItemCategory.CLOTHING)
        assert card2.is_electronics is False

    def test_condition_label_like_new(self):
        card = ItemCard()
        assert card.condition_label == "Like New"

    def test_condition_label_good_for_moderate_defects(self):
        card = ItemCard(
            visible_defects=[DefectSignal(description="scratch", source="visual", severity="moderate")],
        )
        assert card.condition_label == "Good"

    def test_condition_label_fair_for_major_defects(self):
        card = ItemCard(
            visible_defects=[DefectSignal(description="cracked screen", source="visual", severity="major")],
        )
        assert card.condition_label == "Fair"

    def test_all_categories_valid(self):
        for cat in ItemCategory:
            card = ItemCard(category=cat)
            assert card.category == cat

    def test_listing_package_excluded_from_serialization(self):
        card = ItemCard(listing_package={"some": "data"})
        d = card.model_dump()
        assert "listing_package" not in d


# ── DefectSignal ────────────────────────────────────────────────────────────


class TestDefectSignal:
    def test_default_severity(self):
        ds = DefectSignal(description="test", source="visual")
        assert ds.severity == "moderate"

    def test_custom_severity(self):
        ds = DefectSignal(description="test", source="visual", severity="major")
        assert ds.severity == "major"


# ── Job ─────────────────────────────────────────────────────────────────────


class TestJob:
    def test_default_status_created(self):
        job = Job()
        assert job.status == JobStatus.CREATED

    def test_touch_updates_timestamp(self):
        job = Job()
        old = job.updated_at
        import time; time.sleep(0.01)
        job.touch()
        assert job.updated_at >= old

    def test_all_statuses(self):
        for status in JobStatus:
            job = Job(status=status)
            assert job.status == status

    def test_default_fields(self):
        job = Job()
        assert job.video_path is None
        assert job.frame_paths == []
        assert job.item_ids == []
        assert job.total_recovered_value == 0.0
        assert job.error is None

    def test_job_id_auto_generated(self):
        job = Job()
        assert len(job.job_id) == 12

    def test_serialization(self):
        job = Job(job_id="test-123", status=JobStatus.ANALYZING)
        d = job.model_dump()
        assert d["job_id"] == "test-123"
        assert d["status"] == "analyzing"


# ── ListingPackage ──────────────────────────────────────────────────────────


class TestListingPackage:
    def test_hero_image_returns_hero_role(self):
        pkg = ListingPackage(
            item_id="x",
            images=[
                ListingImage(path="/a.jpg", role="secondary"),
                ListingImage(path="/b.jpg", role="hero"),
            ],
        )
        assert pkg.hero_image.path == "/b.jpg"

    def test_hero_image_fallback_to_first(self):
        pkg = ListingPackage(
            item_id="x",
            images=[ListingImage(path="/a.jpg", role="secondary")],
        )
        assert pkg.hero_image.path == "/a.jpg"

    def test_hero_image_none_when_empty(self):
        pkg = ListingPackage(item_id="x")
        assert pkg.hero_image is None

    def test_is_live_anywhere(self):
        pkg = ListingPackage(
            item_id="x",
            platform_listings=[
                PlatformListing(platform="ebay", status=PlatformStatus.FAILED),
                PlatformListing(platform="facebook", status=PlatformStatus.LIVE),
            ],
        )
        assert pkg.is_live_anywhere is True

    def test_not_live_anywhere(self):
        pkg = ListingPackage(
            item_id="x",
            platform_listings=[
                PlatformListing(platform="ebay", status=PlatformStatus.FAILED),
            ],
        )
        assert pkg.is_live_anywhere is False

    def test_default_shipping_policy(self):
        pkg = ListingPackage(item_id="x")
        assert pkg.shipping_policy == "standard"

    def test_v2_fields(self):
        pkg = ListingPackage(
            item_id="x",
            platforms=["ebay", "facebook"],
            prices={"ebay": 800.0},
            research={"ebay": {"avg_sold_price": 800}},
        )
        assert pkg.platforms == ["ebay", "facebook"]
        assert pkg.prices["ebay"] == 800.0


# ── RouteBid ────────────────────────────────────────────────────────────────


class TestRouteBid:
    def test_default_values(self):
        bid = RouteBid(item_id="x", route_type=RouteType.SELL_AS_IS)
        assert bid.viable is True
        assert bid.estimated_value == 0.0
        assert bid.effort == EffortLevel.MODERATE
        assert bid.speed == SpeedEstimate.WEEK

    def test_all_route_types(self):
        for rt in RouteType:
            bid = RouteBid(item_id="x", route_type=rt)
            assert bid.route_type == rt


class TestBestRouteDecision:
    def test_creation(self):
        d = BestRouteDecision(
            item_id="x",
            best_route=RouteType.SELL_AS_IS,
            estimated_best_value=500.0,
        )
        assert d.best_route == RouteType.SELL_AS_IS
        assert d.estimated_best_value == 500.0

    def test_alternatives_default_empty(self):
        d = BestRouteDecision(item_id="x", best_route=RouteType.RETURN)
        assert d.alternatives == []
        assert d.winning_bid is None
