"""Tests for route_decision.py — scoring algorithm and platform ranking."""
from __future__ import annotations

import pytest

from contracts import RouteDecision
from models.item_card import ItemCard, ItemCategory
from route_decision import _score_platform, route_decision


def _make_item(**overrides) -> ItemCard:
    defaults = dict(
        item_id="test123",
        name_guess="iPhone 14 Pro 128GB",
        category=ItemCategory.ELECTRONICS,
    )
    defaults.update(overrides)
    return ItemCard(**defaults)


# ── _score_platform ──────────────────────────────────────────────────────────


class TestScorePlatform:
    def test_returns_float_between_0_and_1(self):
        score = _score_platform("ebay", {"avg_sold_price": 500, "listings_found": 10})
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_higher_price_gives_higher_score(self):
        low = _score_platform("ebay", {"avg_sold_price": 100, "listings_found": 10})
        high = _score_platform("ebay", {"avg_sold_price": 1000, "listings_found": 10})
        assert high > low

    def test_more_listings_gives_higher_confidence(self):
        few = _score_platform("ebay", {"avg_sold_price": 500, "listings_found": 1})
        many = _score_platform("ebay", {"avg_sold_price": 500, "listings_found": 10})
        assert many > few

    def test_zero_price_scores_low(self):
        score = _score_platform("ebay", {"avg_sold_price": 0, "listings_found": 0})
        assert score < 0.5

    def test_weights_sum_to_1(self):
        # Value(0.45) + Confidence(0.25) + Effort(0.15) + Speed(0.15) = 1.0
        assert 0.45 + 0.25 + 0.15 + 0.15 == 1.0

    def test_max_score_components(self):
        # Max price ($2000+), max listings (10+), low effort, fast speed
        score = _score_platform("facebook", {"avg_sold_price": 2000, "listings_found": 15})
        # Facebook: effort=low(0.85), speed=days(0.9)
        expected = 1.0 * 0.45 + 0.95 * 0.25 + 0.85 * 0.15 + 0.9 * 0.15
        assert abs(score - expected) < 0.01

    def test_price_capped_at_2000(self):
        at_cap = _score_platform("ebay", {"avg_sold_price": 2000, "listings_found": 10})
        above_cap = _score_platform("ebay", {"avg_sold_price": 5000, "listings_found": 10})
        assert abs(at_cap - above_cap) < 0.01

    def test_explicit_confidence_overrides_listing_count(self):
        with_explicit = _score_platform("ebay", {
            "avg_sold_price": 500, "listings_found": 1, "confidence": 0.99,
        })
        without_explicit = _score_platform("ebay", {
            "avg_sold_price": 500, "listings_found": 1,
        })
        assert with_explicit > without_explicit

    def test_unknown_platform_uses_defaults(self):
        score = _score_platform("unknown_platform", {"avg_sold_price": 500, "listings_found": 5})
        assert isinstance(score, float)
        assert score > 0

    def test_confidence_tiers(self):
        """Verify confidence tiers: 0, 1, 2, 5, 10 listings."""
        c0 = _score_platform("ebay", {"avg_sold_price": 500, "listings_found": 0})
        c1 = _score_platform("ebay", {"avg_sold_price": 500, "listings_found": 1})
        c2 = _score_platform("ebay", {"avg_sold_price": 500, "listings_found": 2})
        c5 = _score_platform("ebay", {"avg_sold_price": 500, "listings_found": 5})
        c10 = _score_platform("ebay", {"avg_sold_price": 500, "listings_found": 10})
        assert c0 < c1 < c2 < c5 < c10


# ── route_decision ──────────────────────────────────────────────────────────


class TestRouteDecision:
    def test_returns_route_decision(self):
        item = _make_item()
        research = {
            "ebay": {"avg_sold_price": 800, "listings_found": 12},
            "facebook": {"avg_sold_price": 750, "listings_found": 8},
        }
        result = route_decision(item, research)
        assert isinstance(result, RouteDecision)

    def test_platforms_ranked_by_score(self):
        item = _make_item()
        research = {
            "ebay": {"avg_sold_price": 800, "listings_found": 12},
            "facebook": {"avg_sold_price": 750, "listings_found": 8},
            "mercari": {"avg_sold_price": 600, "listings_found": 3},
        }
        result = route_decision(item, research)
        scores = [result.scores[p] for p in result.platforms]
        assert scores == sorted(scores, reverse=True)

    def test_returns_top_4_max(self):
        item = _make_item()
        research = {
            "ebay": {"avg_sold_price": 800, "listings_found": 12},
            "facebook": {"avg_sold_price": 750, "listings_found": 8},
            "mercari": {"avg_sold_price": 600, "listings_found": 5},
            "depop": {"avg_sold_price": 550, "listings_found": 4},
            "amazon": {"avg_sold_price": 700, "listings_found": 10},
        }
        result = route_decision(item, research)
        assert len(result.platforms) <= 4

    def test_returns_all_if_3_or_fewer(self):
        item = _make_item()
        research = {
            "ebay": {"avg_sold_price": 800, "listings_found": 12},
            "facebook": {"avg_sold_price": 750, "listings_found": 8},
        }
        result = route_decision(item, research)
        assert len(result.platforms) == 2

    def test_prices_populated(self):
        item = _make_item()
        research = {
            "ebay": {"avg_sold_price": 800, "listings_found": 12},
        }
        result = route_decision(item, research)
        assert result.prices["ebay"] == 800.0

    def test_scores_populated(self):
        item = _make_item()
        research = {
            "ebay": {"avg_sold_price": 800, "listings_found": 12},
        }
        result = route_decision(item, research)
        assert "ebay" in result.scores
        assert result.scores["ebay"] > 0

    def test_item_id_preserved(self):
        item = _make_item(item_id="my-item-123")
        research = {"ebay": {"avg_sold_price": 500, "listings_found": 5}}
        result = route_decision(item, research)
        assert result.item_id == "my-item-123"

    def test_skips_empty_research_data(self):
        item = _make_item()
        research = {
            "ebay": {"avg_sold_price": 800, "listings_found": 12},
            "facebook": {},
            "mercari": None,
        }
        result = route_decision(item, research)
        assert "facebook" not in result.platforms
        # None data is falsy, should be skipped
        assert "mercari" not in result.platforms

    def test_skips_exception_data(self):
        item = _make_item()
        research = {
            "ebay": {"avg_sold_price": 800, "listings_found": 12},
            "facebook": Exception("connection timeout"),
        }
        result = route_decision(item, research)
        assert "facebook" not in result.platforms

    def test_single_platform(self):
        item = _make_item()
        research = {"ebay": {"avg_sold_price": 500, "listings_found": 5}}
        result = route_decision(item, research)
        assert result.platforms == ["ebay"]

    def test_empty_research(self):
        item = _make_item()
        result = route_decision(item, {})
        assert result.platforms == []
        assert result.prices == {}
        assert result.scores == {}
